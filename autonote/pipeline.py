"""エントリポイント。

  python -m autonote.pipeline ingest       # inbox/ に置かれた記事(Claude が執筆)から「公開待ち」Issue 作成
  python -m autonote.pipeline run          # (予備) Gemini で 調査→執筆→「公開待ち」Issue 作成
  python -m autonote.pipeline promote      # Issue に note の URL が返信されたら: SNS 投稿→Issue を閉じる
  python -m autonote.pipeline instagram    # push後: 保留中の Instagram 投稿
  python -m autonote.pipeline strategy     # 戦略(ジャンル・収益モデル)を今すぐ選び直す
  python -m autonote.pipeline report       # 週次レポート
  python -m autonote.pipeline refresh-tokens  # Threads/Instagram の長期トークン更新

note は機械的な投稿を受け付けないため、公開だけは人が行う:
  1. run が記事・見出し画像・タグを Issue「【公開待ち】…」にまとめる
  2. 人が note に貼り付けて公開し、Issue に note の URL をコメントする
  3. promote が自動で走り、Threads / Instagram に告知して Issue を閉じる
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import traceback
from pathlib import Path

from . import analytics, gh, images, research, sns, writer
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
        "1. note で「投稿」→「テキスト」を開く",
        "2. 下の「タイトル」と「本文」をコピーして貼り付ける",
        f"3. 見出し画像に [この画像]({_image_url(cfg, eyecatch_name)}) を設定する",
        f"4. 公開設定でハッシュタグ `{tags}` を入れる",
    ]
    if paid:
        steps.append(f"5. 有料記事({article['price']}円)にして、✂️ の位置に有料ラインを置く")
    steps.append(f"{len(steps) + 1}. 公開したら、**この Issue に note の URL だけをコメント**する"
                 "(→ Threads / Instagram への告知が自動で始まります)")
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
            "review": {"score": d.get("review_score")}, "sources": d.get("sources", []),
            "sns": d.get("sns"), "writer": d.get("writer", "claude"),
        }
        (STATE_DIR / "drafts").mkdir(parents=True, exist_ok=True)
        (STATE_DIR / "drafts" / f"{slug}.md").write_text(f"# {article['title']}\n\n{body}", encoding="utf-8")
        eye = images.eyecatch(article["title"], strategy.get("genre", ""), slug)
        backed = bool(article["sources"])
        record = {k: v for k, v in article.items() if k != "body_md"}
        record.update(slug=slug, created_at=now().isoformat(), eyecatch=eye.name, data_backed=backed,
                      topic=d.get("topic", article["title"]))
        if cfg["run"]["dry_run"]:
            record["status"] = "dry_run"
        else:
            number = gh.create_issue(f"【公開待ち】{article['title']}",
                                     issue_body(article, slug, eye.name, cfg, backed))
            record.update(status="awaiting_publish", issue=number)
            analytics.notify(f"📝 記事ができました。Issue #{number} の手順で note に公開してください: "
                             f"{article['title']}")
        arts = articles_store.load()
        arts.append(record)
        articles_store.save(arts)
        p.unlink()
    return len(files)


def promote(cfg: dict) -> None:
    """Issue に note の URL がコメントされたときに走る。"""
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
    if rec.get("status") == "published":
        log.info("すでに告知済みです: %s", slug)
        return
    draft = (STATE_DIR / "drafts" / f"{slug}.md").read_text(encoding="utf-8")
    body_md = draft.split("\n\n", 1)[1] if "\n\n" in draft else draft
    article = {**rec, "body_md": body_md}
    sns.promote(article, url, slug, strategy_store.load(), cfg)
    rec.update(status="published", url=url, published_at=now().isoformat())
    articles_store.save(arts)
    gh.comment(number, f"✅ 受け付けました。Threads に告知し、Instagram の投稿を準備しました。\n{url}")
    gh.close(number)


def refresh_tokens() -> None:
    """更新したトークンを state 外の一時ファイルに書き出す(ワークフローが Secrets を更新する)。"""
    out = {}
    for name, fn in (("THREADS_ACCESS_TOKEN", sns.refresh_threads_token),
                     ("IG_ACCESS_TOKEN", sns.refresh_ig_token)):
        try:
            out[name] = fn()
        except Exception as e:  # noqa: BLE001
            log.error("%s の更新に失敗: %s", name, e)
    with open("/tmp/new_tokens.json", "w") as f:
        json.dump(out, f)
    log.info("更新できたトークン: %s", list(out))


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
        elif cmd == "instagram":
            n = sns.flush_instagram(cfg)
            log.info("Instagram 投稿: %d件", n)
        elif cmd == "strategy":
            s = research.select_strategy(cfg)
            analytics.notify(f"🧭 戦略を更新: {s['genre']} / {s['monetization']}"
                             f"(根拠: {'Google検索' if s.get('data_backed') else 'AIの知識のみ'})\n"
                             f"{s.get('reason', '')}")
        elif cmd == "report":
            analytics.notify(analytics.write_report())
        elif cmd == "refresh-tokens":
            refresh_tokens()
        else:
            print(__doc__)
            return 2
    except Exception:  # noqa: BLE001
        log.error(traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
