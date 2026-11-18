"""SNS(Threads / Instagram)用の文面づくり。

投稿は人が投稿キットのボタンから行う(Meta の API は使わない)。
文面は通常、執筆担当の Claude が記事と一緒に用意する。ないときだけ AI で作る。"""
from __future__ import annotations

from . import llm

SNS_SYSTEM = (
    "あなたはSNS運用担当です。宣伝臭を抑え、投稿単体でも読者の役に立つ内容にします。"
    "誇大表現・煽り・根拠のない数字は使いません。"
)


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
