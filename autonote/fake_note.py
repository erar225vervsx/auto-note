"""オフライン検証用の note API スタブ(AUTONOTE_FAKE_NOTE=1 のときだけ使われる)。"""
import random


def respond(path: str) -> dict:
    rnd = random.Random(path)
    if path.startswith("/v3/searches"):
        notes = [{"key": f"n{i}", "name": f"記事{i}", "like_count": rnd.randint(0, 300),
                  "comment_count": rnd.randint(0, 5), "price": rnd.choice([0, 0, 0, 500]),
                  "user": {"urlname": f"u{i}", "follower_count": rnd.randint(0, 5000)}}
                 for i in range(10)]
        return {"data": {"notes": {"contents": notes, "total_count": rnd.randint(50, 5000)}}}
    if "/contents" in path:
        return {"data": {"contents": [{"key": "nabc", "name": "テスト記事のタイトル", "like_count": 12,
                                       "comment_count": 1, "price": 0}], "isLastPage": True}}
    return {}
