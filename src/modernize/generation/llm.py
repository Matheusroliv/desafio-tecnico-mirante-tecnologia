import os

from openai import OpenAI


class OpenAIGenerator:
    def __init__(self) -> None:
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4.1")

    def complete(self, prompt: str) -> str:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY ausente")
        base_url = os.environ.get("OPENAI_BASE_URL") or None
        client = OpenAI(api_key=key, base_url=base_url)
        response = client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {"role": "system", "content": "Siga a politica de traducao do usuario."},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""
