"""オフライン検証用のスタブ応答(AUTONOTE_FAKE_LLM=1 のときだけ使われる)。"""
import json


def respond(prompt: str, system: str) -> str:
    if "ジャンル候補を5つ" in prompt:
        return json.dumps([{"genre": f"ジャンル{i}", "monetization": "paid_article", "reason": "r",
                            } for i in range(2)],
                          ensure_ascii=False)
    if "市場を Google 検索で調べて" in prompt or "あなたの知識で評価して" in prompt:
        return json.dumps({"demand": 7, "competition": 4, "trend": "up", "reader_questions": ["q"],
                           "paid_examples": [], "evidence": "e", "unknowns": ""}, ensure_ascii=False)
    if "最も収益と継続性" in prompt:
        return json.dumps({"genre": "ジャンル0", "monetization": "free_audience", "reason": "テスト",
                           "persona": "会社員", "pillars": ["柱A", "柱B"], "free_paid_mix": "無料中心",
                           "sns_angle": "要点を図解", "avoid": []}, ensure_ascii=False)
    if "記事案を6つ" in prompt:
        return json.dumps({"ideas": [{"title": f"記事案{i}", "keyword": "キーワードA", "angle": "a",
                                      "reader_problem": "p", "evidence": "e", "demand": 7,
                                      "competition": 3, "format": "free", "price": 0}
                                     for i in range(6)]}, ensure_ascii=False)
    if "構成案を作って" in prompt:
        return json.dumps({"title": "テスト記事のタイトル", "lead": "l",
                           "sections": [{"h2": "見出し", "points": ["x"]}],
                           "paywall_after_section": None, "tags": ["#テスト", "AI"]}, ensure_ascii=False)
    if "100点満点で採点" in prompt:
        return json.dumps({"score": 82, "strengths": [], "improvements": [], "blocking_issues": [],
                           "better_title": ""}, ensure_ascii=False)
    if "告知します" in prompt:
        return json.dumps({"threads_posts": ["告知投稿", "要点投稿"],
                           "ig_points": ["要点1", "要点2", "要点3"],
                           "ig_caption": "キャプション #テスト", "ig_cta": "続きはnoteで"},
                          ensure_ascii=False)
    if "本文を書いて" in prompt:
        return "導入文です。\n\n## 見出し1\n\n本文です。\n\n- 箇条書き\n\n## 見出し2\n\n**まとめ**です。"
    return "[]"
