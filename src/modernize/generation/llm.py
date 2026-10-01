"""Porta de LLM e o adaptador OpenAI-compativel.

Qualquer provedor que fale o protocolo de chat completions da OpenAI entra pela
mesma classe trocando ``OPENAI_BASE_URL`` e ``OPENAI_MODEL`` (OpenAI, Ollama, vLLM,
LiteLLM). Parametro especifico de provedor vai em ``OPENAI_EXTRA_BODY`` (JSON),
nunca fixo no codigo.
"""

import json
import os
from typing import Protocol

from modernize.observability.tracing import llm_generation

SYSTEM_PROMPT = (
    "Voce traduz stored procedures PL/pgSQL para modulos Python 3.14. "
    "Siga a politica e o contrato de saida do usuario. Responda apenas com o codigo do modulo."
)


class Generator(Protocol):
    model: str

    def complete(self, prompt: str) -> str: ...


class OpenAIGenerator:
    def __init__(self) -> None:
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4.1")

    def complete(self, prompt: str) -> str:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY ausente")
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=os.environ.get("OPENAI_BASE_URL") or None, timeout=600)
        temperature = 0
        extra_body = _extra_body()
        with llm_generation(
            model=self.model, prompt=prompt, model_parameters={"temperature": temperature}
        ) as generation:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                extra_body=extra_body,
                temperature=temperature,
            )
            text = response.choices[0].message.content or ""
            usage = response.usage
            generation.update(
                output=text,
                usage_details=(
                    {"input": usage.prompt_tokens, "output": usage.completion_tokens, "total": usage.total_tokens}
                    if usage
                    else None
                ),
            )
        return text


def _extra_body() -> dict | None:
    raw = os.environ.get("OPENAI_EXTRA_BODY", "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OPENAI_EXTRA_BODY nao e JSON valido: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("OPENAI_EXTRA_BODY precisa ser um objeto JSON")
    return value
