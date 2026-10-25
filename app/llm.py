"""Meterless Nightshift client. All model calls in the app go through chat()."""
import json
import os

from openai import OpenAI

APP_NAME = "open-agent-hack-why-agent"


def get_client() -> OpenAI:
    token = os.getenv("METERLESS_RUNTIME_TOKEN")
    if not token:
        raise RuntimeError("METERLESS_RUNTIME_TOKEN is not set.")
    return OpenAI(
        api_key=token,
        base_url=os.environ["METERLESS_BASE_URL"],
        default_headers={"meterless-app": APP_NAME, "meterless-scope": "user"},
        timeout=60.0,
        max_retries=1,
    )


def chat(messages: list[dict], temperature: float = 0.2) -> dict:
    """One model call through Nightshift. Returns the text and the model that answered."""
    response = get_client().chat.completions.create(
        model=os.getenv("METERLESS_MODEL", "meterless/auto"),
        messages=messages,
        temperature=temperature,
    )
    return {
        "content": response.choices[0].message.content or "",
        "model": response.model,  # logged on every call: meterless/auto may route to non-NVIDIA models
    }


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (models often wrap it in prose or fences)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("model reply contained no JSON object")
    return json.loads(text[start : end + 1])
