"""Claude API 呼び出し。SDK に依存せず requests で叩く。

AUTONOTE_FAKE_LLM=1 のときはスタブ応答を返す(オフライン検証用)。
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests

from .core import env, log

API_URL = "https://api.anthropic.com/v1/messages"


class LLMError(RuntimeError):
    pass


def complete(prompt: str, *, model: str, system: str = "", max_tokens: int = 4000,
             temperature: float = 0.7, retries: int = 3) -> str:
    if os.environ.get("AUTONOTE_FAKE_LLM"):
        from . import fake_llm
        return fake_llm.respond(prompt, system)

    headers = {
        "x-api-key": env("ANTHROPIC_API_KEY"),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    last = None
    for i in range(retries):
        try:
            r = requests.post(API_URL, headers=headers, json=body, timeout=300)
            if r.status_code in (429, 500, 502, 503, 529):
                raise LLMError(f"retryable {r.status_code}: {r.text[:200]}")
            r.raise_for_status()
            data = r.json()
            return "".join(b.get("text", "") for b in data["content"] if b["type"] == "text")
        except Exception as e:  # noqa: BLE001
            last = e
            wait = 10 * (2 ** i)
            log.warning("LLM 呼び出し失敗(%s)。%s秒後に再試行", e, wait)
            time.sleep(wait)
    raise LLMError(f"LLM 呼び出しに失敗しました: {last}")


def complete_json(prompt: str, *, model: str, system: str = "", max_tokens: int = 4000,
                  temperature: float = 0.4) -> Any:
    """JSON だけを返させ、パースして返す。"""
    sys_prompt = (system + "\n\n" if system else "") + \
        "出力は有効なJSONのみ。前後に説明文やコードフェンスを付けないこと。"
    text = complete(prompt, model=model, system=sys_prompt, max_tokens=max_tokens,
                    temperature=temperature)
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
