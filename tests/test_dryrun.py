"""AI・GitHub・SNS をすべてスタブにして、パイプライン全体を通すテスト。

  python -m pytest tests/  または  python tests/test_dryrun.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_full_flow():
    tmp = Path(tempfile.mkdtemp())
    os.environ.update(AUTONOTE_FAKE_LLM="1", AUTONOTE_FAKE_SNS="1", AUTONOTE_FAKE_GH="1",
                      AUTONOTE_STATE_DIR=str(tmp / "state"), AUTONOTE_PUBLIC_DIR=str(tmp / "public"),
                      AUTONOTE_INBOX_DIR=str(tmp / "inbox"), DRY_RUN="0")
    from autonote import pipeline, sns
    from autonote.core import load_config

    # 1. 毎日の実行: 戦略→ネタ→執筆→公開待ち Issue
    assert pipeline.main(["x", "run"]) == 0
    st = tmp / "state"
    strategy = json.loads((st / "strategy.json").read_text())
    assert strategy["genre"] == "ジャンル0" and strategy["version"] == 2
    assert strategy["data_backed"] is False  # スタブでは検索の出典がないので「根拠なし」と記録される
    arts = json.loads((st / "articles.json").read_text())
    assert arts[0]["status"] == "awaiting_publish" and arts[0]["issue"] == 1
    slug = arts[0]["slug"]
    body = pipeline.issue_body({**arts[0], "body_md": "本文\n<!-- PAYWALL -->\n有料部分"}, slug,
                               arts[0]["eyecatch"], load_config(), False)
    assert f"autonote:slug={slug}" in body and "Issue に note の URL" in body

    # 2. note の URL がコメントされた: SNS 告知
    os.environ.update(ISSUE_NUMBER="1", ISSUE_BODY=body,
                      COMMENT_BODY="公開しました https://note.com/tester/n/n1234abcd")
    assert pipeline.main(["x", "promote"]) == 0
    arts = json.loads((st / "articles.json").read_text())
    assert arts[0]["status"] == "published" and arts[0]["url"].endswith("n1234abcd")
    posts = json.loads((st / "sns_posts.json").read_text())
    assert {p["platform"] for p in posts} == {"threads", "instagram"}
    assert posts[0]["link"].endswith("n1234abcd")
    assert len(list((tmp / "public" / "images").glob("*.png"))) >= 5

    # 二重に告知しないこと
    assert pipeline.main(["x", "promote"]) == 0
    assert len(json.loads((st / "sns_posts.json").read_text())) == len(posts)

    # 3. Instagram の保留投稿
    cfg = load_config()
    assert sns.flush_instagram(cfg) == 1

    # 4. Claude の定期タスクが inbox に置いた記事を取り込む
    (tmp / "inbox").mkdir()
    (tmp / "inbox" / "a.json").write_text(json.dumps({
        "title": "受け口テスト", "body_md": "導入\n\n## 見出し\n\n本文", "tags": ["#AI"],
        "format": "free", "review_score": 85,
        "sources": [{"title": "出典", "url": "https://example.com"}],
        "sns": {"threads_posts": ["告知", "要点"], "ig_points": ["a", "b"], "ig_caption": "c", "ig_cta": "d"},
    }, ensure_ascii=False), encoding="utf-8")
    assert pipeline.main(["x", "ingest"]) == 0
    assert not list((tmp / "inbox").glob("*.json"))
    rec = json.loads((st / "articles.json").read_text())[-1]
    assert rec["status"] == "awaiting_publish" and rec["data_backed"] is True and rec["sns"]["ig_cta"] == "d"
    draft = (st / "drafts" / f"{rec['slug']}.md").read_text()
    assert "AIを活用して作成" in draft  # 定型文が付く
    body2 = pipeline.issue_body({**rec, "body_md": "x"}, rec["slug"], rec["eyecatch"], load_config(), True)
    assert "調査の出典" in body2 and "https://example.com" in body2

    # 5. レポート
    assert pipeline.main(["x", "report"]) == 0
    assert "公開待ち: 1本" in (st / "report.md").read_text()
    assert "公開記事: 1本" in (st / "report.md").read_text()
    print("OK:", tmp)


if __name__ == "__main__":
    test_full_flow()
