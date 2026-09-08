import json
import threading

import httpx
import pytest

from civ7_advisor.advisors import run_all
from civ7_advisor.llm.client import ModelUnavailable, OllamaClient, OllamaUnavailable
from civ7_advisor.llm.prompts import build_prompt, turn_payload
from civ7_advisor.llm.worker import CommentaryWorker


def _transport(models=("gemma4:31b-it-qat",), response=None):
    body = response or {
        "second_opinion": "Hold the frontier [threat.at_war.4].",
        "explain": [{"insight_id": "threat.at_war.4", "text": "War makes this urgent."}],
        "turn_plan": [{"insight_id": "threat.at_war.4", "step": "Move a defender."}],
    }

    def handler(request: httpx.Request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": name} for name in models]})
        payload = json.loads(request.content)
        assert payload["stream"] is False and payload["format"] == "json"
        return httpx.Response(200, json={"response": json.dumps(body)})

    return httpx.MockTransport(handler)


def test_ollama_client_lists_local_model_then_generates():
    client = OllamaClient(transport=_transport())
    assert "second_opinion" in client.generate("evidence")


def test_ollama_client_rejects_missing_cloud_and_remote_models():
    with pytest.raises(ModelUnavailable):
        OllamaClient(transport=_transport(models=("other:latest",))).generate("evidence")
    with pytest.raises(ValueError, match="non-:cloud"):
        OllamaClient(model="gpt-oss:cloud")
    with pytest.raises(ValueError, match="loopback"):
        OllamaClient(base_url="https://ollama.example.com")


def test_ollama_client_reports_local_daemon_unavailable():
    def fail(request):
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(OllamaUnavailable, match="not reachable"):
        OllamaClient(transport=httpx.MockTransport(fail)).generate("evidence")


def test_prompt_is_compact_evidence_json_and_demands_exact_citations(fixture_v2_state):
    insights = run_all(fixture_v2_state)
    prompt, saw_oracle = build_prompt(fixture_v2_state, insights)
    payload = turn_payload(fixture_v2_state, insights)
    assert saw_oracle and "Every claim and every plan step must cite an exact insight id" in prompt
    assert '"insights":' in prompt and "RawLogs" not in prompt and "unit_operations" not in prompt
    assert all("provenance" in item for item in payload["insights"] + payload["intel"])


def test_worker_caches_validated_commentary_per_complete_turn(fixture_state):
    insights = run_all(fixture_state)
    top = insights[0].id

    class FakeClient:
        model = "local:test"
        calls = 0

        def generate(self, prompt):
            self.calls += 1
            return json.dumps({
                "second_opinion": f"Act now [{top}].",
                "explain": [{"insight_id": top, "text": "It matters."}],
                "turn_plan": [{"insight_id": top, "step": "Take the cited action."}],
            })

    client = FakeClient()
    worker = CommentaryWorker(client)  # type: ignore[arg-type]
    worker.schedule(fixture_state, insights)
    result = worker.wait(fixture_state.complete_through_turn)
    assert result.status == "ready" and result.commentary.model == "local:test"
    assert len(result.commentary.prompt_hash) == 64
    worker.schedule(fixture_state, insights)
    assert client.calls == 1


def test_worker_schedule_does_not_wait_for_generation(fixture_state):
    entered, release = threading.Event(), threading.Event()

    class SlowClient:
        model = "local:slow"

        def generate(self, prompt):
            entered.set()
            release.wait(2)
            raise RuntimeError("released")

    worker = CommentaryWorker(SlowClient())  # type: ignore[arg-type]
    worker.schedule(fixture_state, run_all(fixture_state))
    assert entered.wait(1) and worker.result(fixture_state.complete_through_turn).status == "generating"
    release.set()
