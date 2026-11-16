"""LLM・note・SNS をすべてスタブにして、パイプライン全体を通すテスト。

  python -m pytest tests/  または  python tests/test_dryrun.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_full_dry_run():
    tmp = Path(tempfile.mkdtemp())
    os.environ.update(AUTONOTE_FAKE_LLM="1", AUTONOTE_FAKE_NOTE="1", AUTONOTE_FAKE_SNS="1",
                      AUTONOTE_STATE_DIR=str(tmp / "state"), AUTONOTE_PUBLIC_DIR=str(tmp / "public"),
                      DRY_RUN="1", NOTE_URLNAME="tester")
    from autonote import pipeline, sns
    from autonote.core import load_config

    assert pipeline.main(["x", "run"]) == 0
    st = tmp / "state"
    strategy = json.loads((st / "strategy.json").read_text())
    assert strategy["genre"] == "ジャンル0"
    arts = json.loads((st / "articles.json").read_text())
    assert arts and arts[0]["status"] == "dry_run"
    posts = json.loads((st / "sns_posts.json").read_text())
    assert {p["platform"] for p in posts} == {"threads", "instagram"}
    assert len(list((tmp / "public" / "images").glob("*.png"))) >= 5

    # Instagram の保留投稿を処理できること
    for p in posts:
        if p["platform"] == "instagram":
            p["status"] = "pending"
    (st / "sns_posts.json").write_text(json.dumps(posts, ensure_ascii=False))
    cfg = load_config()
    cfg["sns"]["instagram"]["image_base_url"] = "https://example.com/images"
    assert sns.flush_instagram(cfg) == 1

    assert pipeline.main(["x", "report"]) == 0
    assert "運用レポート" in (st / "report.md").read_text()
    print("OK:", tmp)


if __name__ == "__main__":
    test_full_dry_run()
