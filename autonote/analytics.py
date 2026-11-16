"""週次レポートと通知。"""
from __future__ import annotations

import os

import requests

from .core import STATE_DIR, articles_store, log, now, sns_store


def write_report() -> str:
    arts = articles_store.load()
    posts = sns_store.load()
    pub = [a for a in arts if a.get("status") == "published"]
    lines = [f"# 運用レポート({now():%Y-%m-%d})", "",
             f"- 公開記事: {len(pub)}本 / 公開待ち: "
             f"{len([a for a in arts if a.get('status') == 'awaiting_publish'])}本 / 品質不足で見送り: "
             f"{len([a for a in arts if a.get('status') == 'rejected'])}本",
             f"- SNS投稿: Threads {len([p for p in posts if p['platform'] == 'threads' and p.get('status') == 'posted'])}件"
             f" / Instagram {len([p for p in posts if p['platform'] == 'instagram' and p.get('status') == 'posted'])}件",
             f"- エラー: {len([p for p in posts if str(p.get('status', '')).startswith('error')])}件", "",
             "## 最近公開した記事", ""]
    for a in sorted(pub, key=lambda x: x.get("published_at", ""), reverse=True)[:10]:
        lines.append(f"- [{a['title']}]({a.get('url') or ''})")
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
