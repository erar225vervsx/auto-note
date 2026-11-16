"""成果の取り込みと週次レポート。"""
from __future__ import annotations

import os

import requests

from . import note_api
from .core import STATE_DIR, articles_store, log, metrics_store, now, sns_store


def collect(cfg: dict) -> dict:
    urlname = cfg["note"].get("urlname") or os.environ.get("NOTE_URLNAME")
    if not urlname:
        log.warning("note.urlname 未設定のため成果取得をスキップ")
        return {}
    notes = note_api.creator_notes(urlname, pages=5, interval=cfg["research"]["request_interval_sec"])
    arts = articles_store.load()
    by_title = {n["title"]: n for n in notes}
    for a in arts:
        n = by_title.get(a["title"])
        if n:
            a["likes"] = n["likes"]
            a["comments"] = n["comments"]
            if not a.get("url") and n.get("key"):
                a["url"] = f"https://note.com/{urlname}/n/{n['key']}"
    articles_store.save(arts)
    m = {"updated_at": now().isoformat(),
         "articles": [{"title": n["title"], "likes": n["likes"], "comments": n["comments"],
                       "price": n["price"]} for n in notes]}
    metrics_store.save(m)
    return m


def write_report() -> str:
    arts = articles_store.load()
    posts = sns_store.load()
    pub = [a for a in arts if a.get("status") == "published"]
    lines = [f"# 運用レポート({now():%Y-%m-%d})", "",
             f"- 公開記事: {len(pub)}本 / 生成したが公開しなかった記事: "
             f"{len([a for a in arts if a.get('status') == 'rejected'])}本",
             f"- SNS投稿: Threads {len([p for p in posts if p['platform'] == 'threads' and p.get('status') == 'posted'])}件"
             f" / Instagram {len([p for p in posts if p['platform'] == 'instagram' and p.get('status') == 'posted'])}件",
             f"- エラー: {len([p for p in posts if str(p.get('status', '')).startswith('error')])}件", "",
             "## 反応の良い記事", ""]
    for a in sorted(pub, key=lambda x: x.get("likes", 0), reverse=True)[:10]:
        lines.append(f"- スキ{a.get('likes', 0)}: [{a['title']}]({a.get('url') or ''})")
    text = "\n".join(lines) + "\n"
    (STATE_DIR / "report.md").write_text(text, encoding="utf-8")
    return text


def notify(message: str) -> None:
    """Discord / Slack の Incoming Webhook に通知(任意)。"""
    url = os.environ.get("NOTIFY_WEBHOOK_URL")
    if not url or os.environ.get("AUTONOTE_FAKE_SNS"):
        log.info("[通知] %s", message)
        return
    try:
        key = "content" if "discord" in url else "text"
        requests.post(url, json={key: message[:1900]}, timeout=15)
    except Exception as e:  # noqa: BLE001
        log.warning("通知失敗: %s", e)
