"""Minimal Ollama HTTP client, deliberately restricted to loopback."""
from __future__ import annotations

from urllib.parse import urlparse

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gemma4:31b-it-qat"
DEFAULT_TIMEOUT_S = 300.0

# Ollama accepts a JSON Schema in ``format``.  Generic ``"json"`` mode still
# lets models omit fields or stop halfway through a quoted string, which made
# the strict worker validator reject otherwise useful generations.
COMMENTARY_SCHEMA = {
    "type": "object",
    "properties": {
        "second_opinion": {"type": "string", "minLength": 1},
        "explain": {
            "type": "object",
            "additionalProperties": {"type": "string", "minLength": 1},
        },
        "turn_plan": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "insight_id": {"type": "string"},
                    "step": {"type": "string", "minLength": 1},
                },
                "required": ["insight_id", "step"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["second_opinion", "explain", "turn_plan"],
    "additionalProperties": False,
}


class OllamaError(RuntimeError):
    pass


class OllamaUnavailable(OllamaError):
    pass


class ModelUnavailable(OllamaError):
    pass


class OllamaTimeout(OllamaError):
    pass


def _local_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Ollama URL must be an http loopback address")
    return url.rstrip("/")


def _local_model(model: str) -> str:
    if not model.strip() or model.lower().endswith(":cloud"):
        raise ValueError("a local, non-:cloud Ollama model is required")
    return model.strip()


class OllamaClient:
    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL,
                 timeout: float = DEFAULT_TIMEOUT_S,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.model = _local_model(model)
        self.base_url = _local_url(base_url)
        if timeout <= 0:
            raise ValueError("Ollama timeout must be greater than zero")
        self.timeout = timeout
        self._transport = transport

    def generate(self, prompt: str, *, schema: dict | None = None) -> str:
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout,
                              transport=self._transport) as client:
                tags = client.get("/api/tags")
                tags.raise_for_status()
                models = {m.get("name") or m.get("model") for m in tags.json().get("models", [])}
                local_models = {m for m in models if isinstance(m, str) and not m.lower().endswith(":cloud")}
                if self.model not in local_models:
                    raise ModelUnavailable(f"Local Ollama model {self.model!r} is not installed.")
                response = client.post("/api/generate", json={
                    "model": self.model, "prompt": prompt, "stream": False,
                    "format": schema or COMMENTARY_SCHEMA, "keep_alive": "10m",
                    "options": {"temperature": 0.1},
                })
                response.raise_for_status()
                text = response.json().get("response")
                if not isinstance(text, str) or not text.strip():
                    raise OllamaError("Ollama returned no commentary text.")
                return text
        except ModelUnavailable:
            raise
        except httpx.TimeoutException as exc:
            raise OllamaTimeout(f"Ollama exceeded the {self.timeout:.0f}-second timeout.") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise OllamaUnavailable("Ollama is not reachable at the local endpoint.") from exc
