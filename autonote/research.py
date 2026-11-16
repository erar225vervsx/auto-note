"""市場調査・需要調査。

1. 戦略選定(select_strategy): AI がジャンル候補と収益モデル仮説を出し、
   note 上の実データ(スキ数・有料記事の比率と価格・記事数)で裏付けて1つに絞る。
2. 需要調査(build_backlog): 選んだジャンルでキーワードを広げて調べ、
   「需要はあるが良い記事が少ない」切り口を記事ネタの候補として積む。
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
from typing import Any

from . import llm, note_api
from .core import (articles_store, log, metrics_store, now, research_store,
                   strategy_store)


# ------------------------------------------------------------------
# 指標計算
# ------------------------------------------------------------------
def keyword_signals(keyword: str, cfg: dict) -> dict:
    rc = cfg["research"]
    popular = note_api.search_notes(keyword, size=rc["results_per_query"], sort="popular",
                                    interval=rc["request_interval_sec"])
    new = note_api.search_notes(keyword, size=rc["results_per_query"], sort="new",
                                interval=rc["request_interval_sec"])
    likes = [n["likes"] for n in popular] or [0]
    paid = [n for n in popular if n["price"] > 0]
    recent_likes = [n["likes"] for n in new] or [0]
    total = popular[0]["query_total"] if popular else 0
    top = sorted(likes, reverse=True)[:10]
    return {
        "keyword": keyword,
        "total_articles": total,
        "top10_avg_likes": round(statistics.mean(top), 1),
        "median_likes": statistics.median(likes),
        "recent_avg_likes": round(statistics.mean(recent_likes), 1),
        "paid_ratio": round(len(paid) / max(len(popular), 1), 2),
        "paid_avg_price": round(statistics.mean([p["price"] for p in paid]), 0) if paid else 0,
        "paid_avg_likes": round(statistics.mean([p["likes"] for p in paid]), 1) if paid else 0,
        # 上位記事のタイトルは「切り口の重複を避ける」ためだけに使う(本文は取得しない)
        "top_titles": [n["title"] for n in popular[:8]],
        "opportunity": opportunity_score(top, recent_likes, total),
    }


def opportunity_score(top_likes: list[int], recent_likes: list[int], total: int) -> float:
    """需要(上位のスキ数・新着の反応)が高く、競合(記事数)が少ないほど高い。0〜100。"""
    import math
    demand = math.log1p(statistics.mean(top_likes or [0])) * 12
    freshness = math.log1p(statistics.mean(recent_likes or [0])) * 10
    competition = math.log1p(total) * 3
    return round(max(0.0, min(100.0, demand + freshness - competition + 30)), 1)


# ------------------------------------------------------------------
# 戦略選定
# ------------------------------------------------------------------
STRATEGY_SYSTEM = (
    "あなたは note でのコンテンツ事業の戦略担当です。"
    "データに基づいて判断し、AIが継続的に高品質な記事を書けるジャンルを選びます。"
)


def strategy_due(cfg: dict) -> bool:
    s = strategy_store.load()
    if not s:
        return True
    decided = dt.datetime.fromisoformat(s["decided_at"])
    return now() - decided > dt.timedelta(days=cfg["strategy"]["review_interval_days"])


def select_strategy(cfg: dict) -> dict:
    sc = cfg["strategy"]
    model = cfg["writing"]["model"]
    prev = strategy_store.load()
    perf = _own_performance_summary()

    if sc.get("fixed_genre"):
        candidates = [{"genre": sc["fixed_genre"], "monetization": sc["monetization"],
                       "probe_keywords": []}]
        probe = llm.complete_json(
            f"ジャンル「{sc['fixed_genre']}」の需要を測るための note 検索キーワードを"
            f"6個、JSON配列で出してください。", model=model)
        candidates[0]["probe_keywords"] = probe[:6]
    else:
        candidates = llm.complete_json(
            "note で記事を継続販売・発信するためのジャンル候補を6つ提案してください。\n"
            f"制約: {json.dumps(sc['constraints'], ensure_ascii=False)}\n"
            f"収益モデルの指定: {sc['monetization']}(auto なら各候補で最適なものを仮説として選ぶ)\n"
            f"前回の戦略: {json.dumps(prev, ensure_ascii=False)[:1500] if prev else 'なし'}\n"
            f"自分の記事の実績: {perf}\n"
            '形式: [{"genre": "...", "monetization": "paid_article|affiliate|free_audience",'
            ' "reason": "...", "probe_keywords": ["検索語", ...6個]}]',
            model=model, system=STRATEGY_SYSTEM)

    evidence = []
    for c in candidates:
        sigs = [keyword_signals(k, cfg) for k in c["probe_keywords"][:6]]
        sigs = [{k: v for k, v in s.items() if k != "top_titles"} for s in sigs]
        evidence.append({**c, "signals": sigs})
        log.info("候補 %s: 平均機会スコア %.1f", c["genre"],
                 statistics.mean([s["opportunity"] for s in sigs] or [0]))

    decision = llm.complete_json(
        "以下はジャンル候補と、note 上で実際に検索して得た指標です。\n"
        "指標の意味: top10_avg_likes=上位記事の平均スキ, paid_ratio=上位に占める有料記事の割合,"
        " paid_avg_price=有料記事の平均価格, total_articles=記事数(競合の多さ), opportunity=機会スコア\n"
        f"{json.dumps(evidence, ensure_ascii=False)}\n\n"
        f"自分の記事の実績: {perf}\n"
        "最も収益と継続性が見込める組み合わせを1つ選び、運用方針を決めてください。\n"
        "収益モデルは paid_article(有料記事), affiliate(記事内で商品紹介), "
        "free_audience(無料記事でフォロワーを増やす) から選ぶこと。\n"
        '形式: {"genre": "...", "monetization": "...", "reason": "データを根拠に3文以内",'
        ' "persona": "想定読者", "pillars": ["記事の柱となるテーマ", ...3〜5個],'
        ' "free_paid_mix": "無料と有料の比率や使い分けの方針",'
        ' "sns_angle": "Threads/Instagram での見せ方の方針", "avoid": ["避けるべき話題"]}',
        model=model, system=STRATEGY_SYSTEM)

    decision["decided_at"] = now().isoformat()
    decision["evidence"] = evidence
    strategy_store.save(decision)
    log.info("戦略を決定: %s / %s", decision["genre"], decision["monetization"])
    return decision


# ------------------------------------------------------------------
# 記事ネタの候補づくり
# ------------------------------------------------------------------
def build_backlog(cfg: dict, strategy: dict) -> list[dict]:
    model = cfg["writing"]["research_model"]
    done = [a["title"] for a in articles_store.load()][-60:]
    keywords = llm.complete_json(
        f"ジャンル: {strategy['genre']}\n想定読者: {strategy['persona']}\n"
        f"テーマの柱: {json.dumps(strategy['pillars'], ensure_ascii=False)}\n"
        f"note で読者が検索しそうな具体的なキーワード(2〜3語)を{cfg['research']['seed_count']}個、"
        "JSON配列で出してください。既に書いた記事と重複しないこと。\n"
        f"既存記事: {json.dumps(done, ensure_ascii=False)}",
        model=model)

    signals = [keyword_signals(k, cfg) for k in keywords[: cfg["research"]["seed_count"]]]
    signals.sort(key=lambda s: s["opportunity"], reverse=True)

    ideas = llm.complete_json(
        "以下は note での検索結果の指標と、上位記事のタイトルです。\n"
        f"{json.dumps(signals, ensure_ascii=False)}\n\n"
        f"ジャンル: {strategy['genre']} / 収益モデル: {strategy['monetization']}\n"
        f"無料・有料の方針: {strategy.get('free_paid_mix', '')}\n"
        f"避ける話題: {json.dumps(strategy.get('avoid', []), ensure_ascii=False)}\n"
        f"既に書いた記事: {json.dumps(done, ensure_ascii=False)}\n\n"
        "需要があるのに上位記事が答えきれていない切り口を探し、記事案を6つ出してください。"
        "上位記事のタイトルを真似ず、独自の切り口にすること。\n"
        '形式: [{"title": "仮タイトル", "keyword": "狙う検索語", "angle": "既存記事との差別化",'
        ' "reader_problem": "読者の悩み", "format": "free|paid", "price": 0,'
        ' "expected_value": 1〜10}]',
        model=cfg["writing"]["model"])

    sig_by_kw = {s["keyword"]: s for s in signals}
    for i in ideas:
        s = sig_by_kw.get(i.get("keyword"), {})
        i["opportunity"] = s.get("opportunity", 50)
        i["score"] = round(i["opportunity"] * 0.6 + float(i.get("expected_value", 5)) * 4, 1)
        i["status"] = "queued"
        i["created_at"] = now().isoformat()

    data = research_store.load() or {}
    backlog = [b for b in data.get("backlog", []) if b.get("status") == "queued"]
    backlog.extend(ideas)
    backlog.sort(key=lambda b: b["score"], reverse=True)
    research_store.save({"updated_at": now().isoformat(), "signals": signals,
                         "backlog": backlog[:40]})
    return backlog


def pop_topic() -> dict | None:
    data = research_store.load() or {}
    backlog = data.get("backlog", [])
    for b in backlog:
        if b.get("status") == "queued":
            b["status"] = "writing"
            research_store.save(data)
            return b
    return None


def mark_topic(title: str, status: str) -> None:
    data = research_store.load() or {}
    for b in data.get("backlog", []):
        if b.get("title") == title and b.get("status") == "writing":
            b["status"] = status
    research_store.save(data)


def _own_performance_summary() -> str:
    m = metrics_store.load()
    arts = m.get("articles", [])
    if not arts:
        return "まだ実績なし"
    arts = sorted(arts, key=lambda a: a.get("likes", 0), reverse=True)
    top = [f"{a['title']}(スキ{a['likes']})" for a in arts[:5]]
    low = [f"{a['title']}(スキ{a['likes']})" for a in arts[-3:]]
    return f"記事数{len(arts)} / 反応が良い: {top} / 反応が弱い: {low}"
