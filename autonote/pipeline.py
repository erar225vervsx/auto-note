"""エントリポイント。

  python -m autonote.pipeline run          # 毎日: 調査→執筆→公開→SNS→成果取得
  python -m autonote.pipeline instagram    # push後: 保留中の Instagram 投稿
  python -m autonote.pipeline strategy     # 戦略(ジャンル・収益モデル)を今すぐ選び直す
  python -m autonote.pipeline report       # 週次レポート
  python -m autonote.pipeline refresh-tokens  # Threads/Instagram の長期トークン更新
"""
from __future__ import annotations

import json
import random
import sys
import time
import traceback

from . import analytics, images, research, sns, writer
from .core import STATE_DIR, articles_store, load_config, log, now, setup_logging, strategy_store


def _slug(title: str) -> str:
    return f"{now():%Y%m%d-%H%M}-{abs(hash(title)) % 10**6:06d}"


def run(cfg: dict) -> None:
    if cfg["run"]["kill_switch"]:
        log.warning("kill_switch が有効のため終了")
        return
    dry = cfg["run"]["dry_run"]

    # 公開時刻を毎回少しずらす
    jitter = cfg["note"].get("jitter_minutes", 0)
    if jitter and not dry:
        time.sleep(random.randint(0, jitter * 60))

    strategy = research.select_strategy(cfg) if research.strategy_due(cfg) else strategy_store.load()

    queued = [b for b in (research.research_store.load() or {}).get("backlog", [])
              if b.get("status") == "queued"]
    if len(queued) < 3:
        research.build_backlog(cfg, strategy)

    published = []
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
        record.update(slug=slug, created_at=now().isoformat(), topic=topic["title"])

        if not article["publishable"]:
            record["status"] = "rejected"
            research.mark_topic(topic["title"], "rejected")
            analytics.notify(f"⚠️ 品質基準未満のため公開見送り: {article['title']}"
                             f"({article['review']['score']}点)")
        elif dry:
            record["status"] = "dry_run"
            images.eyecatch(article["title"], strategy["genre"], slug)
            sns.promote(article, None, slug, strategy, cfg)
            research.mark_topic(topic["title"], "done")
        else:
            from . import note_publisher
            eye = images.eyecatch(article["title"], strategy["genre"], slug)
            try:
                res = note_publisher.publish(article, cfg, eye)
                record.update(status="published" if res["mode"] == "published" else "draft",
                              url=res.get("url"))
                research.mark_topic(topic["title"], "done")
                if res["mode"] == "published":
                    sns.promote(article, res.get("url"), slug, strategy, cfg)
                    published.append(record)
                else:
                    analytics.notify(f"📝 有料記事を下書き保存しました。確認して公開してください: {article['title']}")
            except Exception as e:  # noqa: BLE001
                record.update(status="error", error=str(e))
                research.mark_topic(topic["title"], "queued")
                analytics.notify(f"❌ note 公開に失敗: {e}")
                arts = articles_store.load()
                arts.append(record)
                articles_store.save(arts)
                raise
        arts = articles_store.load()
        arts.append(record)
        articles_store.save(arts)

    for r in published:
        analytics.notify(f"✅ 公開しました: {r['title']} {r.get('url') or ''}")
    try:
        analytics.collect(cfg)
    except Exception as e:  # noqa: BLE001
        log.warning("成果取得に失敗: %s", e)


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
        if cmd == "run":
            run(cfg)
        elif cmd == "instagram":
            n = sns.flush_instagram(cfg)
            log.info("Instagram 投稿: %d件", n)
        elif cmd == "strategy":
            s = research.select_strategy(cfg)
            analytics.notify(f"🧭 戦略を更新: {s['genre']} / {s['monetization']}\n{s.get('reason', '')}")
        elif cmd == "report":
            analytics.collect(cfg)
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
