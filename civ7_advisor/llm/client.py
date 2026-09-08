"""Minimal Ollama HTTP client, deliberately restricted to loopback."""
from __future__ import annotations

from urllib.parse import urlparse

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gemma4:31b-it-qat"
LLM_TIMEOUT_S = 90.0


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
                 transport: httpx.BaseTransport | None = None) -> None:
        self.model = _local_model(model)
        self.base_url = _local_url(base_url)
        self._transport = transport

    def generate(self, prompt: str) -> str:
        try:
            with httpx.Client(base_url=self.base_url, timeout=LLM_TIMEOUT_S,
                              transport=self._transport) as client:
                tags = client.get("/api/tags")
                tags.raise_for_status()
                models = {m.get("name") or m.get("model") for m in tags.json().get("models", [])}
                local_models = {m for m in models if isinstance(m, str) and not m.lower().endswith(":cloud")}
                if self.model not in local_models:
                    raise ModelUnavailable(f"Local Ollama model {self.model!r} is not installed.")
                response = client.post("/api/generate", json={
                    "model": self.model, "prompt": prompt, "stream": False, "format": "json",
                    "options": {"temperature": 0.2},
                })
                response.raise_for_status()
                text = response.json().get("response")
                if not isinstance(text, str) or not text.strip():
                    raise OllamaError("Ollama returned no commentary text.")
                return text
        except ModelUnavailable:
            raise
        except httpx.TimeoutException as exc:
            raise OllamaTimeout(f"Ollama exceeded the {LLM_TIMEOUT_S:.0f}-second timeout.") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise OllamaUnavailable("Ollama is not reachable at the local endpoint.") from exc
