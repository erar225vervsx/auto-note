"""AI(LLM)呼び出し。モデル名で接続先を切り替える。

- gemini-*  : Google Gemini API(無料枠で使える。GEMINI_API_KEY が必要)
- claude-*  : Claude API(従量課金。ANTHROPIC_API_KEY が必要)

SDK に依存せず requests で叩く。AUTONOTE_FAKE_LLM=1 のときはスタブ応答を返す(オフライン検証用)。
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests

from .core import env, log

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# 無料枠は1分あたりの回数が少ないため、Gemini は呼び出し間隔を空ける
GEMINI_MIN_INTERVAL = float(os.environ.get("GEMINI_MIN_INTERVAL", "15"))
_last_gemini = 0.0
_thinking_supported = True


class LLMError(RuntimeError):
    pass


def complete(prompt: str, *, model: str, system: str = "", max_tokens: int = 4000,
             temperature: float = 0.7, retries: int = 5, json_mode: bool = False) -> str:
    if os.environ.get("AUTONOTE_FAKE_LLM"):
        from . import fake_llm
        return fake_llm.respond(prompt, system)

    call = _gemini if model.startswith("gemini") else _anthropic
    last = None
    for i in range(retries):
        try:
            return call(prompt, model, system, max_tokens, temperature, json_mode)
        except Exception as e:  # noqa: BLE001
            last = e
            wait = 20 * (2 ** i)
            log.warning("AI 呼び出し失敗(%s)。%s秒後に再試行", e, wait)
            time.sleep(wait)
    raise LLMError(f"AI 呼び出しに失敗しました: {last}")


def _gemini(prompt, model, system, max_tokens, temperature, json_mode) -> str:
    global _last_gemini
    wait = GEMINI_MIN_INTERVAL - (time.time() - _last_gemini)
    if wait > 0:
        time.sleep(wait)
    _last_gemini = time.time()
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        # 思考(thinking)にも出力枠が使われるため少し余裕を持たせる
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens + 2048},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    # JSONモード(responseMimeType)は出力が止まらなくなる不具合があるため使わず、
    # プロンプトで指示してパースする。思考は軽めにして応答時間を抑える
    global _thinking_supported
    if _thinking_supported:
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": "low"}
    headers = {"x-goog-api-key": env("GEMINI_API_KEY"), "content-type": "application/json"}
    t0 = time.time()
    r = requests.post(GEMINI_URL.format(model=model), json=body, timeout=180, headers=headers)
    if r.status_code == 400 and _thinking_supported and "thinking" in r.text.lower():
        # 思考レベルの指定に対応していないモデルなら、指定なしでやり直す
        _thinking_supported = False
        body["generationConfig"].pop("thinkingConfig", None)
        r = requests.post(GEMINI_URL.format(model=model), json=body, timeout=180, headers=headers)
    log.info("Gemini %s: %s (%.0f秒)", model, r.status_code, time.time() - t0)
    if r.status_code in (429, 500, 502, 503, 504):
        raise LLMError(f"retryable {r.status_code}: {r.text[:200]}")
    r.raise_for_status()
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        raise LLMError(f"応答が空です: {json.dumps(data, ensure_ascii=False)[:300]}")
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text:
        raise LLMError(f"本文がありません(finishReason={cands[0].get('finishReason')})")
    return text


def _anthropic(prompt, model, system, max_tokens, temperature, json_mode) -> str:
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    r = requests.post(ANTHROPIC_URL, json=body, timeout=300, headers={
        "x-api-key": env("ANTHROPIC_API_KEY"),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    if r.status_code in (429, 500, 502, 503, 529):
        raise LLMError(f"retryable {r.status_code}: {r.text[:200]}")
    r.raise_for_status()
    data = r.json()
    return "".join(b.get("text", "") for b in data["content"] if b["type"] == "text")


def complete_json(prompt: str, *, model: str, system: str = "", max_tokens: int = 4000,
                  temperature: float = 0.4) -> Any:
    """JSON だけを返させ、パースして返す。"""
    sys_prompt = (system + "\n\n" if system else "") + \
        "出力は有効なJSONのみ。前後に説明文やコードフェンスを付けないこと。"
    text = complete(prompt, model=model, system=sys_prompt, max_tokens=max_tokens,
                    temperature=temperature, json_mode=True)
    return parse_json(text)


def parse_json(text: str) -> Any:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 最初の { または [ から最後の } または ] までを切り出して再挑戦
        start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
        end = max(text.rfind("}"), text.rfind("]"))
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise
