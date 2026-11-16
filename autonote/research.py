"""市場調査・需要調査。

note は GitHub などのサーバーからの機械的なアクセスを拒否しているため、note を直接は調べない。
代わりに Gemini API の公式機能「Google 検索によるグラウンディング」で公開情報を調べる
(Google に載っている note 記事・Q&A・SNS の話題なども含む)。結果には出典URLが付く。

1. 戦略選定(select_strategy): AI がジャンル候補と収益モデル仮説を出し、
   候補ごとに検索で需要・競合・有料記事の相場を調べて1つに絞る。
2. 需要調査(build_backlog): 選んだジャンルで読者の悩み・答えきれていない切り口を検索で集め、
   記事ネタの候補として積む。

検索が使えない場合は AI の知識だけで決め、data_backed=False として記録・通知する。
"""
from __future__ import annotations

import datetime as dt
import json

from . import llm
from .core import articles_store, log, metrics_store, now, research_store, strategy_store

STRATEGY_VERSION = 2

STRATEGY_SYSTEM = (
    "あなたは note でのコンテンツ事業の戦略担当です。"
    "推測と事実を区別し、調べて分かったことを根拠に判断します。"
    "AIが継続的に高品質な記事を書けるジャンルを選びます。"
)

RESEARCH_SYSTEM = (
    "あなたは市場調査の担当です。Google 検索で実際に調べ、見つけた事実だけを書きます。"
    "見つからないことは推測で埋めず、不明と書きます。"
)


# ------------------------------------------------------------------
# 検索つき調査
# ------------------------------------------------------------------
def web_research(prompt: str, cfg: dict) -> tuple[dict, list[dict]]:
    """Google 検索つきで調べ、(JSON結果, 出典) を返す。検索が使えなければ SearchUnavailable。"""
    llm.last_sources = []
    result = llm.complete_json(prompt, model=cfg["writing"]["model"], system=RESEARCH_SYSTEM,
                               search=True, max_tokens=4000)
    sources = [s for s in llm.last_sources if s.get("url")]
    return result, sources


def assess_genre(genre: str, cfg: dict) -> dict:
    """1ジャンルの需要・競合・相場を調べる。"""
    prompt = (
        f"ジャンル「{genre}」について、日本の note(note.com)で記事を出す場合の市場を Google 検索で調べてください。\n"
        "調べること: 読者が実際に困っていること・よく検索される疑問、note 上の人気記事や有料記事の例と価格帯、"
        "同じテーマの書き手の多さ(競合)、ここ1年の話題の伸び。\n"
        '形式: {"demand": 1〜10, "competition": 1〜10, "trend": "up|flat|down",'
        ' "reader_questions": ["..."], "paid_examples": [{"title": "...", "price": 数値またはnull}],'
        ' "evidence": "根拠を3文以内", "unknowns": "調べても分からなかったこと"}'
    )
    try:
        data, sources = web_research(prompt, cfg)
        data["sources"] = sources[:8]
        data["data_backed"] = bool(sources)
    except llm.SearchUnavailable as e:
        log.warning("検索つき調査が使えないため、AIの知識だけで評価します: %s", e)
        data = llm.complete_json(prompt.replace("Google 検索で調べてください", "あなたの知識で評価してください"),
                                 model=cfg["writing"]["model"], system=RESEARCH_SYSTEM)
        data["sources"] = []
        data["data_backed"] = False
    data["opportunity"] = opportunity_score(data)
    return data


def opportunity_score(d: dict) -> float:
    """需要が高く、競合が少なく、伸びているほど高い。0〜100。"""
    try:
        demand = float(d.get("demand", 5))
        comp = float(d.get("competition", 5))
    except (TypeError, ValueError):
        demand, comp = 5.0, 5.0
    trend = {"up": 8, "flat": 0, "down": -8}.get(str(d.get("trend", "flat")), 0)
    return round(max(0.0, min(100.0, demand * 6 + (10 - comp) * 4 + trend)), 1)


# ------------------------------------------------------------------
# 戦略選定
# ------------------------------------------------------------------
def strategy_due(cfg: dict) -> bool:
    s = strategy_store.load()
    if not s or s.get("version") != STRATEGY_VERSION:
        return True
    decided = dt.datetime.fromisoformat(s["decided_at"])
    return now() - decided > dt.timedelta(days=cfg["strategy"]["review_interval_days"])


def select_strategy(cfg: dict) -> dict:
    sc = cfg["strategy"]
    model = cfg["writing"]["model"]
    prev = strategy_store.load()
    perf = _own_performance_summary()

    if sc.get("fixed_genre"):
        candidates = [{"genre": sc["fixed_genre"], "monetization": sc["monetization"]}]
    else:
        candidates = llm.complete_json(
            "note で記事を継続販売・発信するためのジャンル候補を5つ提案してください。\n"
            f"制約: {json.dumps(sc['constraints'], ensure_ascii=False)}\n"
            f"収益モデルの指定: {sc['monetization']}(auto なら各候補で最適なものを仮説として選ぶ)\n"
            f"前回の戦略: {json.dumps({k: prev.get(k) for k in ('genre', 'monetization', 'reason')}, ensure_ascii=False) if prev else 'なし'}\n"
            f"自分の記事の実績: {perf}\n"
            '形式: [{"genre": "...", "monetization": "paid_article|affiliate|free_audience", "reason": "..."}]',
            model=model, system=STRATEGY_SYSTEM)[:5]

    evidence = []
    for c in candidates:
        a = assess_genre(c["genre"], cfg)
        evidence.append({**c, "assessment": a})
        log.info("候補 %s: 機会スコア %.1f(根拠あり=%s)", c["genre"], a["opportunity"], a["data_backed"])

    decision = llm.complete_json(
        "以下はジャンル候補と、Google 検索で調べた評価(出典付き)です。\n"
        "demand=需要, competition=競合の多さ, trend=話題の伸び, opportunity=機会スコア, "
        "data_backed=検索の根拠があるか\n"
        f"{json.dumps(evidence, ensure_ascii=False)[:20000]}\n\n"
        f"自分の記事の実績: {perf}\n"
        "最も収益と継続性が見込める組み合わせを1つ選び、運用方針を決めてください。"
        "根拠のある候補を優先すること。\n"
        "収益モデルは paid_article(有料記事), affiliate(記事内で商品紹介), "
        "free_audience(無料記事でフォロワーを増やす) から選ぶこと。\n"
        '形式: {"genre": "...", "monetization": "...", "reason": "調査結果を根拠に3文以内",'
        ' "persona": "想定読者", "pillars": ["記事の柱となるテーマ", ...3〜5個],'
        ' "free_paid_mix": "無料と有料の比率や使い分けの方針",'
        ' "sns_angle": "Threads/Instagram での見せ方の方針", "avoid": ["避けるべき話題"]}',
        model=model, system=STRATEGY_SYSTEM)

    chosen = next((e for e in evidence if e["genre"] == decision.get("genre")), None)
    decision["data_backed"] = bool(chosen and chosen["assessment"]["data_backed"])
    decision["version"] = STRATEGY_VERSION
    decision["decided_at"] = now().isoformat()
    decision["evidence"] = evidence
    strategy_store.save(decision)
    log.info("戦略を決定: %s / %s(根拠あり=%s)", decision["genre"], decision["monetization"],
             decision["data_backed"])
    return decision


# ------------------------------------------------------------------
# 記事ネタの候補づくり
# ------------------------------------------------------------------
def build_backlog(cfg: dict, strategy: dict) -> list[dict]:
    done = [a["title"] for a in articles_store.load()][-60:]
    prompt = (
        f"ジャンル「{strategy['genre']}」、想定読者「{strategy['persona']}」について Google 検索で調べ、"
        "読者が今まさに困っている具体的な疑問と、既存の記事(note を含む)が答えきれていない点を集めてください。\n"
        f"テーマの柱: {json.dumps(strategy['pillars'], ensure_ascii=False)}\n"
        f"避ける話題: {json.dumps(strategy.get('avoid', []), ensure_ascii=False)}\n"
        f"既に書いた記事(重複させない): {json.dumps(done, ensure_ascii=False)}\n"
        f"収益モデル: {strategy['monetization']} / 無料・有料の方針: {strategy.get('free_paid_mix', '')}\n"
        "その上で記事案を6つ出してください。既存記事のタイトルや文章を真似ないこと。\n"
        '形式: {"ideas": [{"title": "仮タイトル", "keyword": "読者が検索しそうな言葉", '
        '"angle": "既存記事との差別化", "reader_problem": "読者の悩み", "evidence": "需要の根拠",'
        ' "demand": 1〜10, "competition": 1〜10, "format": "free|paid", "price": 0}]}'
    )
    try:
        data, sources = web_research(prompt, cfg)
        backed = bool(sources)
    except llm.SearchUnavailable as e:
        log.warning("検索つき調査が使えないため、AIの知識だけで記事案を作ります: %s", e)
        data = llm.complete_json(prompt.replace("Google 検索で調べ、", ""),
                                 model=cfg["writing"]["model"], system=RESEARCH_SYSTEM)
        sources, backed = [], False
    ideas = data.get("ideas", data) if isinstance(data, dict) else data

    for i in ideas:
        i["opportunity"] = opportunity_score(i)
        i["score"] = i["opportunity"]
        i["status"] = "queued"
        i["data_backed"] = backed
        i["created_at"] = now().isoformat()

    stored = research_store.load() or {}
    backlog = [b for b in stored.get("backlog", []) if b.get("status") == "queued"]
    backlog.extend(ideas)
    backlog.sort(key=lambda b: b["score"], reverse=True)
    research_store.save({"updated_at": now().isoformat(), "sources": sources[:10],
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
    arts = sorted(arts, key=lambda a: a.get("score", 0), reverse=True)
    top = [f"{a['title']}(反応{a.get('score', 0)})" for a in arts[:5]]
    low = [f"{a['title']}(反応{a.get('score', 0)})" for a in arts[-3:]]
    return f"記事数{len(arts)} / 反応が良い: {top} / 反応が弱い: {low}"
