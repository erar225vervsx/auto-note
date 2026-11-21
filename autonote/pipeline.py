"""エントリポイント。

  python -m autonote.pipeline ingest       # inbox/ に置かれた記事(Claude が執筆)から「公開待ち」Issue 作成
  python -m autonote.pipeline run          # (予備) Gemini で 調査→執筆→「公開待ち」Issue 作成
  python -m autonote.pipeline promote      # Issue に note の URL が返信されたら: 投稿キットに SNS 投稿ボタンを出す→Issue を閉じる
  python -m autonote.pipeline kits         # 既存の記事すべての投稿キットを作り直す
  python -m autonote.pipeline strategy     # 戦略(ジャンル・収益モデル)を今すぐ選び直す
  python -m autonote.pipeline report       # 週次レポート

投稿ボタンを押すのは人。Claude と GitHub Actions は下書きまでを用意する:
  1. ingest が記事の「投稿キット」(GitHub Pages)と Issue「【公開待ち】…」を作る
  2. 人がキットのボタンで note に貼り付けて公開し、Issue に note の URL をコメントする
  3. promote がキットに Threads の投稿ボタン(公式の Web Intent)を出し、Issue を閉じる
  4. 人がキットのボタンで Threads・Instagram に投稿する
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import traceback
from pathlib import Path

from . import analytics, gh, images, kit, research, sns, writer
from .core import ROOT, STATE_DIR, articles_store, load_config, log, now, setup_logging, strategy_store

INBOX = Path(os.environ.get("AUTONOTE_INBOX_DIR", ROOT / "inbox"))

NOTE_URL_RE = re.compile(r"https://note\.com/[\w\-.]+/n/[\w]+")
SLUG_RE = re.compile(r"<!--\s*autonote:slug=([\w\-]+)\s*-->")


def _slug(title: str) -> str:
    return f"{now():%Y%m%d-%H%M}-{hashlib.md5(title.encode()).hexdigest()[:6]}"


def _image_url(cfg: dict, name: str) -> str:
    base = (cfg["sns"]["instagram"].get("image_base_url") or os.environ.get("IMAGE_BASE_URL", "")).rstrip("/")
    return f"{base}/{name}" if base else name


def issue_body(article: dict, slug: str, eyecatch_name: str, cfg: dict, data_backed: bool) -> str:
    body = article["body_md"]
    paid = article["format"] == "paid"
    body = re.sub(r"^\s*<!--\s*PAYWALL\s*-->\s*$",
                  "\n---\n**✂️ ここから有料(note の公開設定で、この位置に有料ラインを置く)**\n\n---\n",
                  body, flags=re.M)
    tags = " ".join(f"#{t}" for t in article.get("tags", []))
    steps = [
        f"1. **[投稿キットを開く]({kit.kit_url(cfg, slug)})** → ボタンでタイトル・本文・見出し画像・タグをコピーして note に貼り付け、公開",
    ]
    if paid:
        steps.append(f"   - 有料記事({article['price']}円)。✂️ の位置に有料ラインを置く")
    steps.append("2. 公開したら、**この Issue に note の URL だけをコメント**する"
                 "(→ 1〜2分で投稿キットに Threads・Instagram の投稿ボタンが出ます)")
    review = article.get("review", {})
    sources = article.get("sources") or []
    src_lines = (["", "## 調査の出典", *[f"- [{x.get('title') or x.get('url')}]({x.get('url')})" for x in sources[:10]]]
                 if sources else [])
    return "\n".join([
        f"<!-- autonote:slug={slug} -->",
        "## 公開の手順", *steps, "",
        f"- 自己レビュー: {review.get('score', '?')}点 / 需要調査の根拠: {'あり(Google検索)' if data_backed else 'なし(AIの知識のみ)'}",
        f"- 種類: {'有料 ' + str(article['price']) + '円' if paid else '無料'}",
        "",
        f"- ハッシュタグ: {tags}",
        "",
        "## タイトル", "", article["title"], "",
        "## 本文", "", body, "",
        f"![見出し画像]({_image_url(cfg, eyecatch_name)})",
        *src_lines,
    ])


def run(cfg: dict) -> None:
    if cfg["run"]["kill_switch"]:
        log.warning("kill_switch が有効のため終了")
        return
    dry = cfg["run"]["dry_run"]

    strategy = research.select_strategy(cfg) if research.strategy_due(cfg) else strategy_store.load()

    queued = [b for b in (research.research_store.load() or {}).get("backlog", [])
              if b.get("status") == "queued"]
    if len(queued) < 3:
        research.build_backlog(cfg, strategy)

    for _ in range(cfg["run"]["articles_per_run"]):
        topic = research.pop_topic()
        if not topic:
            log.warning("記事ネタがありません")
            break
        article = writer.write_article(topic, strategy, cfg)
        slug = _slug(article["title"])
        (STATE_DIR / "drafts").mkdir(parents=True, exist_ok=True)
        (STATE_DIR / "drafts" / f"{slug}.md").write_text(
            f"# {article['title']}\n\n{article['body_md']}", encoding="utf-8")
        record = {k: v for k, v in article.items() if k != "body_md"}
        record.update(slug=slug, created_at=now().isoformat(), topic=topic["title"],
                      data_backed=topic.get("data_backed", False))

        if not article["publishable"]:
            record["status"] = "rejected"
            research.mark_topic(topic["title"], "rejected")
            analytics.notify(f"⚠️ 品質基準未満のため見送り: {article['title']}"
                             f"({article['review']['score']}点)")
        else:
            eye = images.eyecatch(article["title"], strategy["genre"], slug)
            record["eyecatch"] = eye.name
            research.mark_topic(topic["title"], "done")
            if dry:
                record["status"] = "dry_run"
            else:
                number = gh.create_issue(f"【公開待ち】{article['title']}",
                                         issue_body(article, slug, eye.name, cfg, record["data_backed"]))
                record.update(status="awaiting_publish", issue=number)
                analytics.notify(f"📝 記事ができました。Issue #{number} の手順で note に公開してください: "
                                 f"{article['title']}")
        arts = articles_store.load()
        arts.append(record)
        articles_store.save(arts)


def ingest(cfg: dict) -> int:
    """inbox/*.json(Claude の定期タスクが書いた記事)を取り込み、公開待ち Issue にする。"""
    files = sorted(INBOX.glob("*.json"))
    footer = cfg["writing"].get("footer", "").strip()
    strategy = strategy_store.load() or {}
    for p in files:
        d = json.loads(p.read_text(encoding="utf-8"))
        if not d.get("title") or not d.get("body_md"):
            log.error("必須項目(title/body_md)がないためスキップ: %s", p.name)
            continue
        body = d["body_md"].strip()
        if footer and footer.splitlines()[-1] not in body:
            body += "\n\n" + footer
        slug = _slug(d["title"])
        article = {
            "title": d["title"], "body_md": body,
            "tags": [t.lstrip("#") for t in d.get("tags", [])][:8],
            "format": "paid" if d.get("format") == "paid" else "free",
            "price": int(d.get("price") or 0), "keyword": d.get("keyword"),
            "review": {"score": d.get("review_score"), "reader": d.get("reader_review")}, "sources": d.get("sources", []),
            "sns": d.get("sns"), "writer": d.get("writer", "claude"),
        }
        (STATE_DIR / "drafts").mkdir(parents=True, exist_ok=True)
        (STATE_DIR / "drafts" / f"{slug}.md").write_text(f"# {article['title']}\n\n{body}", encoding="utf-8")
        eye = images.eyecatch(article["title"], strategy.get("genre", ""), slug)
        backed = bool(article["sources"])
        record = {k: v for k, v in article.items() if k != "body_md"}
        record.update(slug=slug, created_at=now().isoformat(), eyecatch=eye.name, data_backed=backed,
                      topic=d.get("topic", article["title"]))
        arts = articles_store.load()
        arts.append(record)
        articles_store.save(arts)
        kit.build(record, body, cfg)  # Instagram 用の画像もここで作る(record に保存される)
        if cfg["run"]["dry_run"]:
            record["status"] = "dry_run"
        else:
            number = gh.create_issue(f"【公開待ち】{article['title']}",
                                     issue_body(article, slug, eye.name, cfg, backed))
            record.update(status="awaiting_publish", issue=number)
            analytics.notify(f"📝 記事ができました。投稿キット: {kit.kit_url(cfg, slug)} "
                             f"(Issue #{number}) {article['title']}")
        arts[-1] = record
        articles_store.save(arts)
        kit.write_index()
        p.unlink()
    return len(files)


def _body_of(slug: str) -> str:
    draft = (STATE_DIR / "drafts" / f"{slug}.md").read_text(encoding="utf-8")
    return draft.split("\n\n", 1)[1] if "\n\n" in draft else draft


def promote(cfg: dict) -> None:
    """Issue に note の URL がコメントされたときに走る。SNS への投稿は人がキットのボタンで行う。"""
    number = int(os.environ["ISSUE_NUMBER"])
    m_url = NOTE_URL_RE.search(os.environ.get("COMMENT_BODY", ""))
    m_slug = SLUG_RE.search(os.environ.get("ISSUE_BODY", ""))
    if not m_url or not m_slug:
        log.info("note の URL か記事の識別子が見つからないため何もしません")
        return
    url, slug = m_url.group(0), m_slug.group(1)
    arts = articles_store.load()
    rec = next((a for a in arts if a.get("slug") == slug), None)
    if not rec:
        raise RuntimeError(f"記事 {slug} の記録が見つかりません")
    rec.update(url=url, published_at=rec.get("published_at") or now().isoformat(), status="published")
    if not rec.get("sns"):
        rec["sns"] = sns.make_copy({**rec, "body_md": _body_of(slug)}, url, strategy_store.load(), cfg)
    kit.build(rec, _body_of(slug), cfg, note_url=url)
    articles_store.save(arts)
    kit.write_index()
    links = "\n".join(f"- [Threadsで投稿 {i + 1}本目]({p['intent']})"
                      for i, p in enumerate(kit.load(slug)["threads"]) if p.get("intent"))
    gh.comment(number, "✅ note の URL を記録しました。下のボタンを押すと、文面が入った状態で Threads が開きます"
                       "(画像つきの Instagram は投稿キットから)。\n\n"
                       f"{links}\n- [投稿キット(Instagram もここから)]({kit.kit_url(cfg, slug)})")
    gh.close(number)


def rebuild_kits(cfg: dict) -> int:
    """既存の記事すべての投稿キットを作り直す。"""
    arts = articles_store.load()
    n = 0
    for rec in arts:
        if rec.get("status") in ("rejected", "dry_run") or not rec.get("slug"):
            continue
        if not (STATE_DIR / "drafts" / f"{rec['slug']}.md").exists():
            continue
        kit.build(rec, _body_of(rec["slug"]), cfg, note_url=rec.get("url"))
        if rec.get("status") == "published_no_sns":
            rec["status"] = "published"
        n += 1
    articles_store.save(arts)
    kit.write_index()
    return n


def main(argv: list[str]) -> int:
    setup_logging()
    cfg = load_config()
    cmd = argv[1] if len(argv) > 1 else "run"
    try:
        if cmd == "ingest":
            log.info("取り込んだ記事: %d本", ingest(cfg))
        elif cmd == "run":
            run(cfg)
        elif cmd == "promote":
            promote(cfg)
        elif cmd == "kits":
            log.info("作り直したキット: %d件", rebuild_kits(cfg))
        elif cmd == "strategy":
            s = research.select_strategy(cfg)
            analytics.notify(f"🧭 戦略を更新: {s['genre']} / {s['monetization']}"
                             f"(根拠: {'Google検索' if s.get('data_backed') else 'AIの知識のみ'})\n"
                             f"{s.get('reason', '')}")
        elif cmd == "report":
            analytics.notify(analytics.write_report())
        else:
            print(__doc__)
            return 2
    except Exception:  # noqa: BLE001
        log.error(traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
