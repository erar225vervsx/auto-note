"""Threads / Instagram への投稿(どちらも Meta の公式API)。"""
from __future__ import annotations

import json
import os
import time

import requests

from . import images, llm
from .core import env, log, now, sns_store

THREADS = "https://graph.threads.net/v1.0"
IG = "https://graph.instagram.com/v21.0"

SNS_SYSTEM = (
    "あなたはSNS運用担当です。宣伝臭を抑え、投稿単体でも読者の役に立つ内容にします。"
    "誇大表現・煽り・根拠のない数字は使いません。"
)


def _fake() -> bool:
    return bool(os.environ.get("AUTONOTE_FAKE_SNS"))


# ------------------------------------------------------------------
# 文面づくり
# ------------------------------------------------------------------
def make_copy(article: dict, url: str | None, strategy: dict, cfg: dict) -> dict:
    return llm.complete_json(
        f"note 記事「{article['title']}」を告知します。\n"
        f"記事本文(冒頭): {article['body_md'][:2500]}\n"
        f"SNSでの見せ方の方針: {strategy.get('sns_angle', '')}\n"
        "次を作ってください。\n"
        "1. threads_posts: Threads 投稿を2本(各450字以内)。1本目は記事の告知(読む理由が伝わる冒頭)、"
        "2本目は記事の要点1つを単体で役立つ形にした投稿(リンクなし)。\n"
        "2. ig_points: Instagram のカード画像に載せる要点を5つ(各40字以内)。\n"
        "3. ig_caption: Instagram のキャプション(600字以内、最後に「詳しくはプロフィールのリンクから」、"
        "関連ハッシュタグ8〜12個)。\n"
        "4. ig_cta: 最後のカードの一文(30字以内)。\n"
        '形式: {"threads_posts": ["...", "..."], "ig_points": [...], "ig_caption": "...", "ig_cta": "..."}',
        model=cfg["writing"]["research_model"], system=SNS_SYSTEM)


# ------------------------------------------------------------------
# Threads
# ------------------------------------------------------------------
def threads_post(text: str, link: str | None = None) -> str:
    if _fake():
        return f"fake-threads-{int(time.time() * 1000)}"
    uid, token = env("THREADS_USER_ID"), env("THREADS_ACCESS_TOKEN")
    params = {"media_type": "TEXT", "text": text[:500], "access_token": token}
    if link:
        params["link_attachment"] = link
    r = requests.post(f"{THREADS}/{uid}/threads", data=params, timeout=30)
    r.raise_for_status()
    cid = r.json()["id"]
    time.sleep(30)  # 公式推奨: コンテナ作成から公開まで少し待つ
    r = requests.post(f"{THREADS}/{uid}/threads_publish",
                      data={"creation_id": cid, "access_token": token}, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def refresh_threads_token() -> str:
    r = requests.get("https://graph.threads.net/refresh_access_token",
                     params={"grant_type": "th_refresh_token",
                             "access_token": env("THREADS_ACCESS_TOKEN")}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


# ------------------------------------------------------------------
# Instagram(カルーセル投稿)
# ------------------------------------------------------------------
def _ig_wait(cid: str, token: str) -> None:
    for _ in range(30):
        r = requests.get(f"{IG}/{cid}", params={"fields": "status_code", "access_token": token},
                         timeout=30)
        status = r.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Instagram のメディア処理エラー: {cid}")
        time.sleep(5)
    raise RuntimeError("Instagram のメディア処理がタイムアウトしました")


def instagram_carousel(image_urls: list[str], caption: str) -> str:
    if _fake():
        return f"fake-ig-{int(time.time() * 1000)}"
    uid, token = env("IG_USER_ID"), env("IG_ACCESS_TOKEN")
    children = []
    for u in image_urls[:10]:
        r = requests.post(f"{IG}/{uid}/media", data={"image_url": u, "is_carousel_item": "true",
                                                    "access_token": token}, timeout=60)
        r.raise_for_status()
        children.append(r.json()["id"])
    for c in children:
        _ig_wait(c, token)
    r = requests.post(f"{IG}/{uid}/media", data={"media_type": "CAROUSEL", "children": ",".join(children),
                                                "caption": caption[:2200], "access_token": token},
                      timeout=60)
    r.raise_for_status()
    cid = r.json()["id"]
    _ig_wait(cid, token)
    r = requests.post(f"{IG}/{uid}/media_publish", data={"creation_id": cid, "access_token": token},
                      timeout=60)
    r.raise_for_status()
    return r.json()["id"]


def refresh_ig_token() -> str:
    r = requests.get("https://graph.instagram.com/refresh_access_token",
                     params={"grant_type": "ig_refresh_token",
                             "access_token": env("IG_ACCESS_TOKEN")}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


# ------------------------------------------------------------------
# 記事1本分の SNS 展開
# ------------------------------------------------------------------
def promote(article: dict, url: str | None, slug: str, strategy: dict, cfg: dict) -> None:
    sc = cfg["sns"]
    dry = cfg["run"]["dry_run"]
    copy = make_copy(article, url, strategy, cfg)
    history = sns_store.load()

    if sc["threads"]["enabled"]:
        for i, text in enumerate(copy["threads_posts"][: sc["threads"]["posts_per_article"]]):
            link = url if i == 0 else None
            entry = {"platform": "threads", "slug": slug, "text": text, "link": link,
                     "at": now().isoformat()}
            if dry:
                entry["status"] = "dry_run"
            else:
                try:
                    entry["id"] = threads_post(text, link)
                    entry["status"] = "posted"
                except Exception as e:  # noqa: BLE001
                    entry["status"] = f"error: {e}"
                    log.error("Threads 投稿失敗: %s", e)
            history.append(entry)

    if sc["instagram"]["enabled"]:
        paths = images.insta_cards(article["title"], copy["ig_points"], copy["ig_cta"], slug)
        # 画像は公開URLが必要。リポジトリに push された後の段階(instagram ステージ)で投稿する
        history.append({"platform": "instagram", "slug": slug, "caption": copy["ig_caption"],
                        "images": [p.name for p in paths],
                        "status": "dry_run" if dry else "pending", "at": now().isoformat()})
    sns_store.save(history)


def flush_instagram(cfg: dict) -> int:
    """push 済みの画像を使って、保留中の Instagram 投稿を処理する。"""
    base = (cfg["sns"]["instagram"].get("image_base_url") or os.environ.get("IMAGE_BASE_URL", "")).rstrip("/")
    history = sns_store.load()
    done = 0
    for h in history:
        if h.get("platform") != "instagram" or h.get("status") != "pending":
            continue
        if not base:
            log.error("image_base_url が未設定のため Instagram 投稿をスキップ")
            break
        urls = [f"{base}/{name}" for name in h["images"]]
        if not _fake():
            ok = all(requests.head(u, timeout=20).status_code == 200 for u in urls)
            if not ok:
                log.info("画像がまだ公開されていないため次回に回します: %s", h["slug"])
                continue
        try:
            h["id"] = instagram_carousel(urls, h["caption"])
            h["status"] = "posted"
            done += 1
        except Exception as e:  # noqa: BLE001
            h["status"] = f"error: {e}"
            log.error("Instagram 投稿失敗: %s", e)
    sns_store.save(history)
    return done
