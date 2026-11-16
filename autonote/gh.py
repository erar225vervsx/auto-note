"""GitHub Issue の操作(記事の「公開待ち」受け渡しに使う)。

GitHub Actions が自動で用意する GITHUB_TOKEN を使うので、追加のキーは不要。
AUTONOTE_FAKE_GH=1 のときは実際には呼ばない(オフライン検証用)。
"""
from __future__ import annotations

import os

import requests

from .core import env, log

API = "https://api.github.com"
LABEL = "note公開待ち"


def _fake() -> bool:
    return bool(os.environ.get("AUTONOTE_FAKE_GH"))


def _req(method: str, path: str, **kw):
    repo = env("GITHUB_REPOSITORY")
    r = requests.request(method, f"{API}/repos/{repo}{path}", timeout=30, headers={
        "Authorization": f"Bearer {env('GITHUB_TOKEN')}",
        "Accept": "application/vnd.github+json",
    }, **kw)
    r.raise_for_status()
    return r.json() if r.text else {}


def create_issue(title: str, body: str) -> int:
    if _fake():
        log.info("[fake] Issue 作成: %s", title)
        return 1
    return _req("POST", "/issues", json={"title": title, "body": body[:65000], "labels": [LABEL]})["number"]


def comment(number: int, body: str) -> None:
    if _fake():
        log.info("[fake] Issue #%s にコメント: %s", number, body[:80])
        return
    _req("POST", f"/issues/{number}/comments", json={"body": body})


def close(number: int) -> None:
    if _fake():
        log.info("[fake] Issue #%s を閉じる", number)
        return
    _req("PATCH", f"/issues/{number}", json={"state": "closed", "state_reason": "completed"})
