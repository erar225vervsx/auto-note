"""設定・状態ファイル・ログなどの共通処理。"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("AUTONOTE_STATE_DIR", ROOT / "state"))
PUBLIC_DIR = Path(os.environ.get("AUTONOTE_PUBLIC_DIR", ROOT / "public"))
JST = dt.timezone(dt.timedelta(hours=9))

log = logging.getLogger("autonote")


def setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def now() -> dt.datetime:
    return dt.datetime.now(JST)


def load_config(path: str | os.PathLike | None = None) -> dict[str, Any]:
    p = Path(path or os.environ.get("AUTONOTE_CONFIG", ROOT / "config.yaml"))
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # 環境変数での上書き(GitHub Actions の手動実行用)
    if os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"):
        cfg["run"]["dry_run"] = True
    return cfg


def env(name: str, required: bool = True) -> str | None:
    v = os.environ.get(name)
    if required and not v:
        raise RuntimeError(f"環境変数 {name} が設定されていません")
    return v


class JsonStore:
    """state/ 配下の JSON を読み書きする。GitHub Actions ではコミットして永続化する。"""

    def __init__(self, name: str, default: Any):
        self.path = STATE_DIR / f"{name}.json"
        self.default = default

    def load(self) -> Any:
        if not self.path.exists():
            return json.loads(json.dumps(self.default))
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def save(self, data: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        tmp.replace(self.path)


# 状態ファイル一覧
strategy_store = JsonStore("strategy", {})          # 選定中のジャンル・収益モデル
research_store = JsonStore("research", {})          # 直近の需要調査結果
articles_store = JsonStore("articles", [])          # 生成・公開した記事の履歴
sns_store = JsonStore("sns_posts", [])              # SNS 投稿履歴
metrics_store = JsonStore("metrics", {})            # 成果(スキ数・PV等)のスナップショット
tokens_store = JsonStore("tokens", {})              # トークン期限の記録(値そのものは保存しない)
