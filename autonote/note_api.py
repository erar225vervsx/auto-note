"""note の公開エンドポイント(非公式)からの読み取り。

※ note 社が公開しているAPIではないため、仕様が予告なく変わる可能性がある。
  レスポンスの形が違っても落ちないよう、取り出しは防御的に書いている。
"""
from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import quote

import requests

from .core import log

BASE = "https://note.com/api"
UA = "Mozilla/5.0 (compatible; autonote-research/1.0)"
_last_call = 0.0


def _get(path: str, interval: float = 2.0) -> Any:
    global _last_call
    if os.environ.get("AUTONOTE_FAKE_NOTE"):
        from . import fake_note
        return fake_note.respond(path)
    wait = interval - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()
    r = requests.get(BASE + path, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.json()


def _dig(d: Any, *keys: str, default: Any = None) -> Any:
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def _normalize(n: dict) -> dict:
    user = n.get("user") or {}
    return {
        "key": n.get("key"),
        "title": n.get("name") or n.get("title") or "",
        "likes": int(n.get("like_count") or 0),
        "comments": int(n.get("comment_count") or 0),
        "price": int(n.get("price") or 0),
        "author": user.get("urlname"),
        "author_followers": int(user.get("follower_count") or 0),
        "published_at": n.get("publish_at") or n.get("publishAt"),
        "hashtags": [
            (h.get("hashtag") or {}).get("name", "") if isinstance(h, dict) else str(h)
            for h in (n.get("hashtags") or [])
        ],
    }


def search_notes(query: str, *, size: int = 20, sort: str = "popular",
                 interval: float = 2.0) -> list[dict]:
    """キーワードで記事を検索。sort: popular / new / like"""
    path = f"/v3/searches?context=note&q={quote(query)}&size={size}&start=0&sort={sort}"
    try:
        data = _get(path, interval)
    except Exception as e:  # noqa: BLE001
        log.warning("note 検索失敗 q=%s: %s", query, e)
        return []
    notes = _dig(data, "data", "notes", "contents") or _dig(data, "data", "notes") or []
    if isinstance(notes, dict):
        notes = notes.get("contents") or []
    total = _dig(data, "data", "notes", "total_count") or len(notes)
    out = [_normalize(n) for n in notes if isinstance(n, dict)]
    for o in out:
        o["query_total"] = total
    return out


def creator_notes(urlname: str, pages: int = 3, interval: float = 2.0) -> list[dict]:
    """自分(または任意のクリエイター)の公開記事一覧。成果の取り込みに使う。"""
    out: list[dict] = []
    for page in range(1, pages + 1):
        try:
            data = _get(f"/v2/creators/{quote(urlname)}/contents?kind=note&page={page}", interval)
        except Exception as e:  # noqa: BLE001
            log.warning("記事一覧の取得失敗: %s", e)
            break
        contents = _dig(data, "data", "contents") or []
        out.extend(_normalize(c) for c in contents if isinstance(c, dict))
        if _dig(data, "data", "isLastPage", default=True):
            break
    return out
