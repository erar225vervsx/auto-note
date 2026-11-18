"""投稿キット: note・Threads・Instagram に「ボタンを押すだけ」で投稿するための下書き一式。

Meta の API は使わない。GitHub Pages で公開する docs/kit/ のページが、
docs/kits/<slug>.json を読み込み、コピー用ボタン・Threads の公式投稿リンク(Web Intent)・
Instagram への共有ボタンを表示する。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote

import markdown as md

from . import images
from .core import ROOT, articles_store, now

DOCS = Path(os.environ.get("AUTONOTE_DOCS_DIR", ROOT / "docs"))
THREADS_INTENT = "https://www.threads.com/intent/post"


def _base(cfg: dict, key: str) -> str:
    return (cfg.get("kit", {}).get(key) or "").rstrip("/")


def kit_url(cfg: dict, slug: str) -> str:
    return f"{_base(cfg, 'page_url')}/?a={slug}"


def threads_intent(text: str, url: str | None = None) -> str:
    q = f"text={quote(text)}"
    if url:
        q += f"&url={quote(url, safe='')}"
    return f"{THREADS_INTENT}?{q}"


def build(rec: dict, body_md: str, cfg: dict, note_url: str | None = None) -> Path:
    """記事1本分のキットを作る(何度呼んでもよい。note の URL が分かったら呼び直す)。"""
    slug = rec["slug"]
    img_base = _base(cfg, "image_base_url")
    sns = rec.get("sns") or {}
    ig_names = rec.get("ig_images")
    if not ig_names and sns.get("ig_points"):
        paths = images.insta_cards(rec["title"], sns["ig_points"], sns.get("ig_cta", "続きはnoteで"), slug)
        ig_names = [p.name for p in paths]
        rec["ig_images"] = ig_names
    threads = []
    for i, text in enumerate(sns.get("threads_posts", [])[:2]):
        link = note_url if i == 0 else None
        threads.append({"text": text, "link": link,
                        "intent": threads_intent(text, link) if (i > 0 or note_url) else None})
    kit = {
        "slug": slug,
        "title": rec["title"],
        "format": rec.get("format", "free"),
        "price": rec.get("price", 0),
        "tags": rec.get("tags", []),
        "body_md": body_md,
        "body_html": md.markdown(body_md.replace("<!-- PAYWALL -->", "\n\n---\n\n✂️ ここから有料\n\n---\n\n"),
                                 extensions=["extra", "sane_lists"]),
        "eyecatch": f"{img_base}/{rec['eyecatch']}" if rec.get("eyecatch") else None,
        "note_url": note_url,
        "threads": threads,
        "instagram": {"caption": sns.get("ig_caption", ""),
                      "images": [f"{img_base}/{n}" for n in (ig_names or [])]},
        "updated_at": now().isoformat(),
    }
    out = DOCS / "kits" / f"{slug}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(kit, ensure_ascii=False, indent=1), encoding="utf-8")
    write_index()
    return out


def load(slug: str) -> dict:
    return json.loads((DOCS / "kits" / f"{slug}.json").read_text(encoding="utf-8"))


def write_index() -> None:
    """キット一覧(新しい順)。ブックマーク1つで全記事のキットに行けるようにする。"""
    items = []
    for a in reversed(articles_store.load()):
        if (DOCS / "kits" / f"{a.get('slug')}.json").exists():
            items.append({"slug": a["slug"], "title": a["title"], "status": a.get("status"),
                          "format": a.get("format", "free"), "created_at": a.get("created_at")})
    (DOCS / "kits").mkdir(parents=True, exist_ok=True)
    (DOCS / "kits" / "index.json").write_text(json.dumps(items[:60], ensure_ascii=False, indent=1),
                                              encoding="utf-8")
