import json
import threading
from copy import deepcopy

import httpx
import pytest

from civ7_advisor.advisors import run_all
from civ7_advisor.llm.client import ModelUnavailable, OllamaClient, OllamaUnavailable
from civ7_advisor.llm.prompts import build_prompt, turn_payload
from civ7_advisor.llm.worker import CommentaryWorker
from tests.factories import game_state


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


def test_even_empty_full_state_commentary_is_oracle_seen():
    prompt, saw_oracle = build_prompt(game_state(), [])
    assert saw_oracle and '"provenance":"oracle"' in prompt


def test_worker_caches_validated_commentary_per_complete_turn(fixture_state):
    insights = run_all(fixture_state)
    top = [item.id for item in insights[:3]]

    class FakeClient:
        model = "local:test"
        calls = 0

        def generate(self, prompt):
            self.calls += 1
            return json.dumps({
                "second_opinion": f"Act now [{top[0]}].",
                "explain": [{"insight_id": item, "text": "It matters."} for item in top],
                "turn_plan": [{"insight_id": top[0], "step": "Take the cited action."}],
            })

    client = FakeClient()
    worker = CommentaryWorker(client)  # type: ignore[arg-type]
    worker.schedule(fixture_state, insights)
    result = worker.wait(fixture_state.complete_through_turn)
    assert result.status == "ready" and result.commentary.model == "local:test"
    assert len(result.commentary.prompt_hash) == 64
    worker.schedule(fixture_state, insights)
    assert client.calls == 1


def test_worker_same_turn_with_changed_prompt_does_not_reuse_old_game_commentary(fixture_state):
    state = deepcopy(fixture_state)
    insights = run_all(state)
    top = [item.id for item in insights[:3]]

    class FakeClient:
        model = "local:test"
        calls = 0

        def generate(self, prompt):
            self.calls += 1
            return json.dumps({
                "second_opinion": f"Generation {self.calls} [{top[0]}].",
                "explain": [{"insight_id": item, "text": "Why."} for item in top],
                "turn_plan": [{"insight_id": top[0], "step": "Act."}],
            })

    client = FakeClient()
    worker = CommentaryWorker(client)  # type: ignore[arg-type]
    worker.schedule(state, insights)
    assert worker.wait(state.complete_through_turn).status == "ready"
    state.turns[state.complete_through_turn][0] = (
        state.turns[state.complete_through_turn][0].__class__(
            **(state.turns[state.complete_through_turn][0].__dict__ | {"gold": 999.0})
        )
    )
    worker.schedule(state, insights)
    result = worker.wait(state.complete_through_turn)
    assert client.calls == 2 and "Generation 2" in result.commentary.second_opinion


def test_worker_rejects_partial_top_three_explanations(fixture_state):
    insights = run_all(fixture_state)

    class PartialClient:
        model = "local:test"

        def generate(self, prompt):
            return json.dumps({
                "second_opinion": "Incomplete.",
                "explain": [{"insight_id": insights[0].id, "text": "Only one."}],
                "turn_plan": [{"insight_id": insights[0].id, "step": "Act."}],
            })

    worker = CommentaryWorker(PartialClient())  # type: ignore[arg-type]
    worker.schedule(fixture_state, insights)
    result = worker.wait(fixture_state.complete_through_turn)
    assert result.status == "error" and "every requested top insight" in result.message


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
