"""記事の執筆と自己レビュー。

構成案 → 本文 → 第三者視点のレビュー(採点) → 基準未満なら1回だけ改稿 → それでも未満なら公開しない。
"""
from __future__ import annotations

import json
import re

from . import llm
from .core import log

WRITER_SYSTEM = (
    "あなたは note で読まれる記事を書くプロの編集者兼ライターです。"
    "読者の具体的な悩みに答え、手順・具体例・判断基準を必ず入れます。"
    "確かめられない数値・統計・固有の事実は書かず、一般論として書くか、読者に確認を促します。"
    "医療・法律・投資について断定的な助言はしません。他人の記事の文章を真似しません。"
)

REVIEW_SYSTEM = (
    "あなたは厳しい編集長です。記事を公開してよいかを判断します。"
    "甘い採点はせず、読者にとっての価値と誤情報リスクを最優先で見ます。"
)


def write_article(topic: dict, strategy: dict, cfg: dict) -> dict:
    wc = cfg["writing"]
    model = wc["model"]
    paid = topic.get("format") == "paid"

    outline = llm.complete_json(
        f"記事案: {json.dumps(topic, ensure_ascii=False)}\n"
        f"想定読者: {strategy['persona']}\n"
        f"収益モデル: {strategy['monetization']}\n"
        "この記事の構成案を作ってください。"
        + ("有料記事なので、無料部分で読者の悩みと記事で得られることを明確にし、"
           "有料部分に具体的な手順・テンプレート・事例を置く構成にすること。" if paid else "")
        + '\n形式: {"title": "32文字以内の魅力的なタイトル", "lead": "導入の要点",'
          ' "sections": [{"h2": "見出し", "points": ["書く内容"]}],'
          ' "paywall_after_section": 有料境界を置く見出しの番号(無料記事はnull),'
          ' "tags": ["ハッシュタグ(#なし)", ...5〜8個]}',
        model=model, system=WRITER_SYSTEM)

    body = _draft(outline, topic, strategy, cfg)
    review = _review(outline["title"], body, topic, cfg)
    log.info("初稿レビュー: %s点", review["score"])

    if review["score"] < cfg["run"]["min_quality_score"]:
        body = llm.complete(
            f"以下の記事を、編集長の指摘に従って全面的に改稿してください。"
            f"見出し構成はMarkdown(## と ###)のまま、本文のみを出力すること。\n\n"
            f"# 指摘\n{json.dumps(review, ensure_ascii=False)}\n\n# 記事\n{body}",
            model=model, system=WRITER_SYSTEM, max_tokens=12000)
        review = _review(outline["title"], body, topic, cfg)
        log.info("改稿レビュー: %s点", review["score"])

    body = body.strip() + "\n\n" + wc.get("footer", "").strip()
    return {
        "title": review.get("better_title") or outline["title"],
        "body_md": body,
        "tags": [t.lstrip("#") for t in outline.get("tags", [])][:8],
        "format": "paid" if paid else "free",
        "price": int(topic.get("price") or (wc["price_options"][0] if paid else 0)),
        "keyword": topic.get("keyword"),
        "review": review,
        "publishable": review["score"] >= cfg["run"]["min_quality_score"]
                       and not review.get("blocking_issues"),
    }


def _draft(outline: dict, topic: dict, strategy: dict, cfg: dict) -> str:
    wc = cfg["writing"]
    return llm.complete(
        f"次の構成案で note 記事の本文を書いてください。\n"
        f"構成案: {json.dumps(outline, ensure_ascii=False)}\n"
        f"読者の悩み: {topic.get('reader_problem')}\n差別化: {topic.get('angle')}\n"
        f"文体: {wc['tone']}\n文字数: {wc['min_chars']}〜{wc['max_chars']}字\n"
        f"収益モデル: {strategy['monetization']}"
        + ("(商品やサービスを紹介する場合は、[[LINK:商品名]] のように仮のリンク記法で書くこと。"
           "実在のURLを推測で書かない)" if strategy["monetization"] == "affiliate" else "")
        + "\n\n出力ルール:\n- タイトルは書かず、導入文から始める\n"
          "- 見出しは Markdown の ## と ### を使う\n"
          "- 有料境界を置く場合はその位置に単独行で <!-- PAYWALL --> と書く\n"
          "- 箇条書き・太字は適度に使い、スマホで読みやすい短い段落にする",
        model=wc["model"], system=WRITER_SYSTEM, max_tokens=12000)


def _review(title: str, body: str, topic: dict, cfg: dict) -> dict:
    return llm.complete_json(
        f"タイトル: {title}\n狙う検索語: {topic.get('keyword')}\n読者の悩み: {topic.get('reader_problem')}\n\n"
        f"{body}\n\n"
        "この記事を100点満点で採点してください。観点: 悩みへの回答の具体性、独自性、読みやすさ、"
        "誤情報・誇大表現・規約違反のリスク(リスクがあれば大きく減点)。\n"
        '形式: {"score": 0〜100, "strengths": ["..."], "improvements": ["具体的な修正指示"],'
        ' "blocking_issues": ["公開してはいけない理由があれば。なければ空配列"],'
        ' "better_title": "より良いタイトル案(32文字以内)"}',
        model=cfg["writing"]["model"], system=REVIEW_SYSTEM, temperature=0.2)


def split_paywall(body_md: str) -> tuple[str, str | None]:
    parts = re.split(r"^\s*<!--\s*PAYWALL\s*-->\s*$", body_md, maxsplit=1, flags=re.M)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return body_md, None
