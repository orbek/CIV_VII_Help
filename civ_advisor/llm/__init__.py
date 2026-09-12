"""Optional local Ollama commentary; deterministic advice never depends on it."""

from .client import DEFAULT_MODEL, OllamaClient
from .models import Commentary, CommentaryResult, Explanation, PlanStep
from .worker import CommentaryWorker

__all__ = ["Commentary", "CommentaryResult", "CommentaryWorker", "DEFAULT_MODEL", "Explanation",
           "OllamaClient", "PlanStep"]
