import json
import threading
from copy import deepcopy

import httpx
import pytest

from civ_advisor.advisors import run_all
from civ_advisor.llm.client import COMMENTARY_SCHEMA, ModelUnavailable, OllamaClient, OllamaUnavailable
from civ_advisor.llm.prompts import build_prompt, response_schema, turn_payload
from civ_advisor.llm.worker import CommentaryWorker
from tests.factories import game_state, snapshot


def _transport(models=("gemma4:31b-it-qat",), response=None):
    body = response or {
        "second_opinion": "Hold the frontier [threat.at_war.4].",
        "explain": {"threat.at_war.4": "War makes this urgent."},
        "turn_plan": [{"insight_id": "threat.at_war.4", "step": "Move a defender."}],
    }

    def handler(request: httpx.Request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": name} for name in models]})
        payload = json.loads(request.content)
        assert payload["stream"] is False and payload["format"] == COMMENTARY_SCHEMA
        assert payload["keep_alive"] == "10m" and payload["options"]["temperature"] == 0.1
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
    prompt, saw_oracle, cited = build_prompt(fixture_v2_state, insights)
    payload = turn_payload(fixture_v2_state, insights)
    assert saw_oracle and "Every claim and every plan step must cite an exact insight id" in prompt
    assert '"insights":' in prompt and "RawLogs" not in prompt and "unit_operations" not in prompt
    assert all("provenance" in item for item in payload["insights"] + payload["intel"])
    assert cited == [i.id for i in insights]


def test_fair_prompt_omits_every_oracle_fact_rather_than_hiding_the_result(fixture_v2_state):
    """Fair mode used to hide all commentary because every prompt shipped the Oracle
    tactical block. Filter the evidence instead: the fair prompt must contain no oracle
    row at all, and must therefore be safe to show."""
    insights = run_all(fixture_v2_state)
    assert any(i.provenance.value == "oracle" for i in insights), "fixture must have intercepts"
    prompt, saw_oracle, cited = build_prompt(fixture_v2_state, insights, oracle=False)
    assert saw_oracle is False
    assert '"provenance":"oracle"' not in prompt and '"tactical":' not in prompt
    assert cited and all(
        next(i for i in insights if i.id == cid).provenance.value == "fair" for cid in cited)


def test_response_schema_pins_explanation_count_and_citation_ids():
    schema = response_schema(["top.a", "top.b"], {"top.a", "top.b", "other.c"})
    explain = schema["properties"]["explain"]
    plan = schema["properties"]["turn_plan"]
    assert explain["required"] == ["top.a", "top.b"]
    assert set(explain["properties"]) == {"top.a", "top.b"}
    assert explain["additionalProperties"] is False
    assert plan["items"]["properties"]["insight_id"]["enum"] == ["other.c", "top.a", "top.b"]


def test_empty_full_state_commentary_still_declares_the_oracle_tactical_block():
    """The tactical block is Oracle by source even when its lists are empty, so an
    oracle-mode prompt that includes it must report saw_oracle."""
    prompt, saw_oracle, _ = build_prompt(game_state(), [])
    assert saw_oracle and '"provenance":"oracle"' in prompt


def test_worker_caches_validated_commentary_per_complete_turn(fixture_state):
    insights = run_all(fixture_state)
    top = [item.id for item in insights[:3]]

    class FakeClient:
        model = "local:test"
        calls = 0

        def generate(self, prompt, *, schema=None):
            self.calls += 1
            return json.dumps({
                "second_opinion": f"Act now [{top[0]}].",
                "explain": {item: "It matters." for item in top},
                "turn_plan": [{"insight_id": top[0], "step": "Take the cited action."}],
            })

    client = FakeClient()
    worker = CommentaryWorker(client)  # type: ignore[arg-type]
    snap = snapshot(fixture_state, insights)
    worker.schedule(snap)
    result = worker.wait(snap)
    assert result.status == "ready" and result.commentary.model == "local:test"
    assert len(result.commentary.prompt_hash) == 64
    identity = result.commentary.identity
    assert identity.session == "session-1" and identity.evidence_mode == "oracle"
    assert identity.snapshot_revision == 1 and identity.turn == snap.analysis_turn
    assert identity.insight_ids == tuple(i.id for i in insights)
    worker.schedule(snap)
    assert client.calls == 1


def test_worker_same_turn_with_changed_prompt_does_not_reuse_old_game_commentary(fixture_state):
    state = deepcopy(fixture_state)
    insights = run_all(state)
    top = [item.id for item in insights[:3]]

    class FakeClient:
        model = "local:test"
        calls = 0

        def generate(self, prompt, *, schema=None):
            self.calls += 1
            return json.dumps({
                "second_opinion": f"Generation {self.calls} [{top[0]}].",
                "explain": {item: "Why." for item in top},
                "turn_plan": [{"insight_id": top[0], "step": "Act."}],
            })

    client = FakeClient()
    worker = CommentaryWorker(client)  # type: ignore[arg-type]
    worker.schedule(snapshot(state, insights))
    assert worker.wait(snapshot(state, insights)).status == "ready"
    state.turns[state.complete_through_turn][0] = (
        state.turns[state.complete_through_turn][0].__class__(
            **(state.turns[state.complete_through_turn][0].__dict__ | {"gold": 999.0})
        )
    )
    worker.schedule(snapshot(state, insights, revision=2))
    result = worker.wait(snapshot(state, insights, revision=2))
    assert client.calls == 2 and "Generation 2" in result.commentary.second_opinion


def test_worker_rejects_partial_top_three_explanations(fixture_state):
    insights = run_all(fixture_state)

    class PartialClient:
        model = "local:test"

        def generate(self, prompt, *, schema=None):
            return json.dumps({
                "second_opinion": "Incomplete.",
                "explain": {insights[0].id: "Only one."},
                "turn_plan": [{"insight_id": insights[0].id, "step": "Act."}],
            })

    worker = CommentaryWorker(PartialClient())  # type: ignore[arg-type]
    snap = snapshot(fixture_state, insights)
    worker.schedule(snap)
    result = worker.wait(snap)
    assert result.status == "error" and "evidence-backed advice above is still complete" in result.message


def test_worker_schedule_does_not_wait_for_generation(fixture_state):
    entered, release = threading.Event(), threading.Event()

    class SlowClient:
        model = "local:slow"

        def generate(self, prompt, *, schema=None):
            entered.set()
            release.wait(2)
            raise RuntimeError("released")

    worker = CommentaryWorker(SlowClient())  # type: ignore[arg-type]
    snap = snapshot(fixture_state)
    worker.schedule(snap)
    assert entered.wait(1) and worker.result(snap).status == "generating"
    release.set()


def test_worker_coalesces_log_burst_into_latest_pending_prompt(fixture_state):
    entered, release, second_started = threading.Event(), threading.Event(), threading.Event()
    insights = run_all(fixture_state)
    top = [item.id for item in insights[:3]]

    class BurstClient:
        model = "local:slow"
        calls = 0

        def generate(self, prompt, *, schema=None):
            self.calls += 1
            if self.calls == 1:
                entered.set()
                release.wait(2)
            else:
                second_started.set()
            return json.dumps({
                "second_opinion": f"Generation {self.calls} [{top[0]}].",
                "explain": {item: "Why." for item in top},
                "turn_plan": [{"insight_id": top[0], "step": "Act."}],
            })

    client = BurstClient()
    worker = CommentaryWorker(client)  # type: ignore[arg-type]
    first = deepcopy(fixture_state)
    second = deepcopy(fixture_state)
    latest = deepcopy(fixture_state)
    second.turns[second.complete_through_turn][0] = second.turns[second.complete_through_turn][0].__class__(
        **(second.turns[second.complete_through_turn][0].__dict__ | {"gold": 998.0})
    )
    latest.turns[latest.complete_through_turn][0] = latest.turns[latest.complete_through_turn][0].__class__(
        **(latest.turns[latest.complete_through_turn][0].__dict__ | {"gold": 999.0})
    )

    worker.schedule(snapshot(first, insights, revision=1))
    assert entered.wait(1)
    worker.schedule(snapshot(second, insights, revision=2))
    latest_snapshot = snapshot(latest, insights, revision=3)
    worker.schedule(latest_snapshot)
    release.set()
    assert second_started.wait(1)
    result = worker.wait(latest_snapshot)
    assert result.status == "ready" and "Generation 2" in result.commentary.second_opinion
    assert client.calls == 2
    worker.close()


def _variant(state, gold: float):
    """The same state with one number changed, so it produces a different prompt digest."""
    copy = deepcopy(state)
    row = copy.turns[copy.complete_through_turn][0]
    copy.turns[copy.complete_through_turn][0] = row.__class__(**(row.__dict__ | {"gold": gold}))
    return copy


def test_a_replaced_pending_prompt_can_still_be_generated_later(fixture_state):
    """A -> B -> C -> B must not leave B spinning forever.

    B is queued, then replaced by C before it ever starts. The old worker cached B's
    placeholder as "generating", so when B's evidence came round again it was treated as
    already in flight and nothing ever ran: a permanent spinner. Scheduling B again must
    actually generate it.
    """
    entered, release = threading.Event(), threading.Event()
    insights = run_all(fixture_state)
    top = [item.id for item in insights[:3]]

    class Client:
        model = "local:test"
        calls = 0

        def generate(self, prompt, *, schema=None):
            self.calls += 1
            if self.calls == 1:
                entered.set()
                release.wait(2)
            return json.dumps({
                "second_opinion": f"Generation {self.calls} [{top[0]}].",
                "explain": {item: "Why." for item in top},
                "turn_plan": [{"insight_id": top[0], "step": "Act."}],
            })

    client = Client()
    worker = CommentaryWorker(client)  # type: ignore[arg-type]
    a = snapshot(fixture_state, insights, revision=1)
    b = snapshot(_variant(fixture_state, 111.0), insights, revision=2)
    c = snapshot(_variant(fixture_state, 222.0), insights, revision=3)

    worker.schedule(a)
    assert entered.wait(1)
    worker.schedule(b)                       # queued behind A
    assert worker.result(b).status == "queued"
    worker.schedule(c)                       # replaces B before it ever starts
    release.set()
    assert worker.wait(c, timeout=3).status == "ready"

    worker.schedule(b)                       # B's evidence comes round again
    result = worker.wait(b, timeout=3)
    assert result.status == "ready", f"B is stuck in {result.status}"
    assert "Generation 3" in result.commentary.second_opinion
    worker.close()


def test_an_older_turn_finishing_late_does_not_become_the_current_commentary(fixture_state):
    """The result for the turn that was asked about is the result that is returned."""
    insights = run_all(fixture_state)
    top = [item.id for item in insights[:3]]

    class Client:
        model = "local:test"
        calls = 0

        def generate(self, prompt, *, schema=None):
            self.calls += 1
            return json.dumps({
                "second_opinion": f"Generation {self.calls} [{top[0]}].",
                "explain": {item: "Why." for item in top},
                "turn_plan": [{"insight_id": top[0], "step": "Act."}],
            })

    worker = CommentaryWorker(Client())  # type: ignore[arg-type]
    old = snapshot(fixture_state, insights, revision=1)
    new = snapshot(_variant(fixture_state, 999.0), insights, revision=2)
    worker.wait(old, timeout=3)
    current = worker.wait(new, timeout=3)
    assert current.commentary.identity.snapshot_revision == 2
    assert "Generation 2" in current.commentary.second_opinion
    worker.close()


def test_fair_mode_generates_its_own_commentary_instead_of_hiding_everything(fixture_v2_state):
    insights = run_all(fixture_v2_state)
    fair_ids = [i.id for i in insights if i.provenance.value == "fair"]
    assert fair_ids, "fixture must have fair insights"
    top = fair_ids[:3]

    class Client:
        model = "local:test"

        def generate(self, prompt, *, schema=None):
            assert '"provenance":"oracle"' not in prompt   # the fair prompt saw no intercepts
            return json.dumps({
                "second_opinion": f"Fair call [{top[0]}].",
                "explain": {item: "Why." for item in top},
                "turn_plan": [{"insight_id": top[0], "step": "Act."}],
            })

    worker = CommentaryWorker(Client())  # type: ignore[arg-type]
    snap = snapshot(fixture_v2_state, insights)
    result = worker.wait(snap, oracle=False, timeout=3)
    assert result.status == "ready" and result.commentary.saw_oracle is False
    assert result.commentary.identity.evidence_mode == "fair"
    assert set(result.commentary.identity.insight_ids) == set(fair_ids)
    worker.close()


def test_earlier_prose_is_offered_only_as_dated_history_in_the_same_session_and_mode(fixture_state):
    entered, release = threading.Event(), threading.Event()
    insights = run_all(fixture_state)
    top = [item.id for item in insights[:3]]

    class Client:
        model = "local:test"
        calls = 0

        def generate(self, prompt, *, schema=None):
            self.calls += 1
            if self.calls == 2:
                entered.set()
                release.wait(2)
            return json.dumps({
                "second_opinion": f"Generation {self.calls} [{top[0]}].",
                "explain": {item: "Why." for item in top},
                "turn_plan": [{"insight_id": top[0], "step": "Act."}],
            })

    worker = CommentaryWorker(Client())  # type: ignore[arg-type]
    first = snapshot(fixture_state, insights, revision=1)
    assert worker.wait(first, timeout=3).status == "ready"

    second = snapshot(_variant(fixture_state, 42.0), insights, revision=2)
    worker.schedule(second)
    assert entered.wait(1)
    pending = worker.result(second)
    assert pending.status == "generating" and pending.commentary is None
    assert pending.previous is not None and "Generation 1" in pending.previous.second_opinion

    # Another session is a different sitting: its history must not be offered at all.
    other = snapshot(_variant(fixture_state, 43.0), insights, session="session-2", revision=1)
    assert worker.result(other).previous is None
    release.set()
    worker.close()
