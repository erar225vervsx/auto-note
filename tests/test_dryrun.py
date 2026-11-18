"""AI・GitHub をすべてスタブにして、記事の取り込み → 投稿キット → URL コメントまでを通すテスト。

  python -m pytest tests/  または  python tests/test_dryrun.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_full_flow():
    tmp = Path(tempfile.mkdtemp())
    os.environ.update(AUTONOTE_FAKE_LLM="1", AUTONOTE_FAKE_SNS="1", AUTONOTE_FAKE_GH="1",
                      AUTONOTE_STATE_DIR=str(tmp / "state"), AUTONOTE_PUBLIC_DIR=str(tmp / "public"),
                      AUTONOTE_INBOX_DIR=str(tmp / "inbox"), AUTONOTE_DOCS_DIR=str(tmp / "docs"),
                      DRY_RUN="0")
    from autonote import pipeline
    from autonote.core import load_config

    st, docs = tmp / "state", tmp / "docs" / "kits"

    # 1. Claude の定期タスクが inbox に置いた記事を取り込む → 投稿キットと公開待ち Issue
    (tmp / "inbox").mkdir()
    (tmp / "inbox" / "a.json").write_text(json.dumps({
        "title": "受け口テスト", "body_md": "導入\n\n## 見出し\n\n本文\n\n<!-- PAYWALL -->\n\n有料部分",
        "tags": ["#AI", "仕事術"], "format": "paid", "price": 300, "review_score": 85,
        "sources": [{"title": "出典", "url": "https://example.com"}],
        "sns": {"threads_posts": ["告知の文面", "要点の文面"], "ig_points": ["a", "b", "c"],
                "ig_caption": "キャプション #AI", "ig_cta": "続きはnoteで"},
    }, ensure_ascii=False), encoding="utf-8")
    assert pipeline.main(["x", "ingest"]) == 0
    assert not list((tmp / "inbox").glob("*.json"))
    rec = json.loads((st / "articles.json").read_text())[-1]
    slug = rec["slug"]
    assert rec["status"] == "awaiting_publish" and rec["data_backed"] is True
    assert len(rec["ig_images"]) == 5  # 表紙 + 要点3 + 誘導
    k = json.loads((docs / f"{slug}.json").read_text())
    assert k["note_url"] is None and k["threads"][0]["intent"] is None  # URL が来るまで告知ボタンは出さない
    assert k["threads"][1]["intent"].startswith("https://www.threads.com/intent/post?text=")
    assert "<h2>" in k["body_html"] and "ここから有料" in k["body_html"]
    assert "AIを活用して作成" in k["body_md"]  # 定型文が付く
    assert len(k["instagram"]["images"]) == 5 and k["eyecatch"].endswith("-eyecatch.png")
    idx = json.loads((docs / "index.json").read_text())
    assert idx[0]["slug"] == slug and idx[0]["status"] == "awaiting_publish"

    body = pipeline.issue_body({**rec, "body_md": k["body_md"]}, slug, rec["eyecatch"], load_config(), True)
    assert f"autonote:slug={slug}" in body and "投稿キットを開く" in body and f"?a={slug}" in body
    assert "調査の出典" in body and "有料記事(300円)" in body

    # 2. note の URL がコメントされた → キットに Threads の投稿ボタン、Issue を閉じる
    os.environ.update(ISSUE_NUMBER="1", ISSUE_BODY=body,
                      COMMENT_BODY="公開しました https://note.com/tester/n/n1234abcd")
    assert pipeline.main(["x", "promote"]) == 0
    rec = json.loads((st / "articles.json").read_text())[-1]
    assert rec["status"] == "published" and rec["url"].endswith("n1234abcd")
    k = json.loads((docs / f"{slug}.json").read_text())
    q = parse_qs(urlparse(k["threads"][0]["intent"]).query)
    assert q["text"] == ["告知の文面"] and q["url"] == ["https://note.com/tester/n/n1234abcd"]
    assert "url" not in parse_qs(urlparse(k["threads"][1]["intent"]).query)

    # 3. 既存記事のキットを作り直せる(SNS 待ちだった記事は公開済みにそろえる)
    arts = json.loads((st / "articles.json").read_text())
    arts[-1]["status"] = "published_no_sns"
    (st / "articles.json").write_text(json.dumps(arts, ensure_ascii=False))
    assert pipeline.main(["x", "kits"]) == 0
    assert json.loads((st / "articles.json").read_text())[-1]["status"] == "published"

    # 4. レポート
    assert pipeline.main(["x", "report"]) == 0
    assert "公開記事: 1本" in (st / "report.md").read_text()
    print("OK:", tmp)


if __name__ == "__main__":
    test_full_flow()
