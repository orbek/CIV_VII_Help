"""The persistent player record: atomic writes, recoverable damage, explicit association."""
from __future__ import annotations

import json

import pytest

from civ_advisor.context_store import (
    ACKNOWLEDGED,
    GOAL,
    SCHEMA_VERSION,
    WATCH,
    PersistentContextStore,
    StoreError,
)


def store(tmp_path, name: str = "notes.json") -> PersistentContextStore:
    held = PersistentContextStore(path=tmp_path / name)
    held.load()
    return held


def test_entries_survive_a_restart_of_the_same_sitting(tmp_path):
    first = store(tmp_path)
    first.adopt("s1", 1, "seeds-1-2")
    first.record(GOAL, "decision.culture.C", 33, text="level with the field by turn 100")
    first.record(ACKNOWLEDGED, "decision.food.C", 33, fingerprint="fp1")

    second = store(tmp_path)
    second.adopt("s1", 1, "seeds-1-2")
    assert {e.kind for e in second.entries.values()} == {GOAL, ACKNOWLEDGED}
    assert second.of_kind(GOAL)[0].text == "level with the field by turn 100"
    assert second.applies("decision.food.C", "fp1")
    assert second.pending == ()


def test_a_new_sitting_holds_the_old_entries_back_instead_of_applying_them(tmp_path):
    """An acknowledgement carried silently across a reload could hide a live alert."""
    first = store(tmp_path)
    first.adopt("s1", 1, "seeds-1-2")
    first.record(ACKNOWLEDGED, "decision.culture.C", 33, fingerprint="fp1")

    second = store(tmp_path)
    second.adopt("s2", 2, "seeds-1-2", epoch_reason="logs_wiped")
    assert second.entries == {}
    assert second.applies("decision.culture.C", "fp1") is False
    [held] = second.pending
    assert held.session == "s1" and held.count == 1
    # The same seeds are not proof of the same line of play, and it says so.
    assert "same save seeds" in held.reason
    assert "can be branched" in held.reason


def test_a_different_save_is_reported_as_almost_certainly_another_game(tmp_path):
    first = store(tmp_path)
    first.adopt("s1", 1, "seeds-1-2")
    first.record(GOAL, "decision.culture.C", 33, text="x")
    second = store(tmp_path)
    second.adopt("s2", 2, "seeds-9-9")
    [held] = second.pending
    assert "different save seeds" in held.reason and "another game" in held.reason


def test_an_unidentifiable_save_says_so_rather_than_guessing(tmp_path):
    first = store(tmp_path)
    first.adopt("s1", 1, None)
    first.record(GOAL, "decision.culture.C", 33, text="x")
    second = store(tmp_path)
    second.adopt("s2", 2, None)
    [held] = second.pending
    assert "could not be identified" in held.reason


def test_association_is_explicit_and_re_files_the_entries(tmp_path):
    first = store(tmp_path)
    first.adopt("s1", 1, "seeds-1-2")
    first.record(ACKNOWLEDGED, "decision.culture.C", 33, fingerprint="fp1")
    second = store(tmp_path)
    second.adopt("s2", 2, "seeds-1-2")
    adopted = second.associate("s1", 1)
    assert [e.session for e in adopted] == ["s2"]
    assert second.applies("decision.culture.C", "fp1")
    assert second.pending == ()
    # And it survives the next restart as this sitting's own record.
    third = store(tmp_path)
    third.adopt("s2", 2, "seeds-1-2")
    assert third.applies("decision.culture.C", "fp1")


def test_held_entries_can_be_discarded(tmp_path):
    first = store(tmp_path)
    first.adopt("s1", 1, None)
    first.record(GOAL, "a", 1, text="x")
    first.record(WATCH, "b", 1)
    second = store(tmp_path)
    second.adopt("s2", 2, None)
    assert second.discard("s1", 1) == 2
    assert second.pending == ()
    third = store(tmp_path)
    third.adopt("s2", 2, None)
    assert third.entries == {} and third.pending == ()


def test_associating_something_that_is_not_held_is_an_error(tmp_path):
    held = store(tmp_path)
    held.adopt("s1", 1, None)
    with pytest.raises(StoreError, match="no held entries"):
        held.associate("nope", 7)


def test_recording_without_a_session_or_with_an_unknown_kind_is_refused(tmp_path):
    held = store(tmp_path)
    with pytest.raises(StoreError, match="no current session"):
        held.record(GOAL, "a", 1)
    held.adopt("s1", 1, None)
    with pytest.raises(StoreError, match="not one of"):
        held.record("whatever", "a", 1)


def test_an_acknowledgement_stops_applying_when_its_fingerprint_moves(tmp_path):
    """It has not been withdrawn; the evidence behind the decision changed."""
    held = store(tmp_path)
    held.adopt("s1", 1, None)
    held.record(ACKNOWLEDGED, "decision.culture.C", 33, fingerprint="fp1")
    assert held.applies("decision.culture.C", "fp1")
    assert held.applies("decision.culture.C", "fp2") is False


def test_the_file_is_written_whole_and_leaves_no_temporary_behind(tmp_path):
    held = store(tmp_path)
    held.adopt("s1", 1, None)
    held.record(GOAL, "a", 1, text="x")
    raw = json.loads((tmp_path / "notes.json").read_text())
    assert raw["schema_version"] == SCHEMA_VERSION and raw["revision"] >= 1
    assert [e["kind"] for e in raw["entries"]] == [GOAL]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["notes.json"]


def test_a_damaged_store_is_moved_aside_and_reported_not_dropped(tmp_path):
    (tmp_path / "notes.json").write_text("{not json at all")
    held = store(tmp_path)
    assert held.entries == {}
    assert held.last_error and "could not be read" in held.last_error
    assert "moved to" in held.last_error
    # The player's file still exists under another name, for recovery by hand.
    aside = [p for p in tmp_path.iterdir() if ".broken-" in p.name]
    assert len(aside) == 1 and aside[0].read_text() == "{not json at all"


def test_a_store_from_a_future_version_is_left_alone(tmp_path):
    (tmp_path / "notes.json").write_text(json.dumps({"schema_version": 99, "entries": []}))
    held = store(tmp_path)
    assert held.entries == {}
    assert "not 1" in held.last_error and "left alone" in held.last_error
    # Untouched, so a newer build can still read it.
    assert json.loads((tmp_path / "notes.json").read_text())["schema_version"] == 99


def test_a_store_with_unexpected_entry_fields_is_quarantined(tmp_path):
    (tmp_path / "notes.json").write_text(json.dumps(
        {"schema_version": SCHEMA_VERSION, "entries": [{"surprise": 1}]}))
    held = store(tmp_path)
    assert held.entries == {} and held.last_error
    assert [p for p in tmp_path.iterdir() if ".broken-" in p.name]


def test_a_write_failure_is_reported_and_the_entry_still_applies_for_now(tmp_path):
    held = PersistentContextStore(path=tmp_path / "unwritable" / "notes.json")
    held.load()
    held.adopt("s1", 1, None)
    (tmp_path / "unwritable").write_text("this is a file, not a directory")
    entry = held.record(GOAL, "a", 1, text="x")
    assert entry.id in held.entries              # still in effect for this session
    assert held.last_error and "could not be saved" in held.last_error
    assert "will not survive a restart" in held.last_error


def test_forgetting_an_entry_moves_the_revision_and_persists(tmp_path):
    held = store(tmp_path)
    held.adopt("s1", 1, None)
    entry = held.record(WATCH, "a", 1)
    before = held.revision
    assert held.forget(entry.id) is True
    assert held.revision == before + 1
    assert held.forget(entry.id) is False
    again = store(tmp_path)
    again.adopt("s1", 1, None)
    assert again.entries == {}


def test_adopting_the_same_sitting_twice_keeps_what_is_held(tmp_path):
    """The read path calls this on every request; recomputing must not discard the
    entries waiting to be associated."""
    first = store(tmp_path)
    first.adopt("s1", 1, None)
    first.record(GOAL, "a", 1, text="x")
    second = store(tmp_path)
    second.adopt("s2", 2, None)
    assert len(second.pending) == 1
    for _ in range(3):
        second.adopt("s2", 2, None)
    assert len(second.pending) == 1


def test_the_context_path_is_namespaced_per_game(tmp_path):
    from civ_advisor.context_store import store_path_for

    assert store_path_for("civ7", base=tmp_path) == tmp_path / "civ7" / "player-context.json"
    assert store_path_for("civ6", base=tmp_path) != store_path_for("civ7", base=tmp_path)


def test_an_entry_records_the_game_it_was_made_in(tmp_path):
    store = PersistentContextStore(path=tmp_path / "notes.json")
    store.load()
    store.adopt("s1", 1, None, game="civ7")
    entry = store.record(kind="acknowledged", subject="x", turn=10, game="civ7")
    assert entry.game == "civ7"
    raw = json.loads((tmp_path / "notes.json").read_text())
    assert raw["entries"][0]["game"] == "civ7"


def test_another_game_s_entries_are_neither_applied_nor_offered(tmp_path):
    """Spec 8.1: offering an acknowledgement across the boundary would repeat exactly
    the mistake the reload logic exists to prevent."""
    store = PersistentContextStore(path=tmp_path / "notes.json")
    store.load()
    store.adopt("s1", 1, None, game="civ7")
    store.record(kind="acknowledged", subject="x", turn=10, game="civ7")

    store.adopt("s2", 2, None, game="civ6")
    assert store.of_kind("acknowledged") == ()
    assert all(a.session != "s1" for a in store.pending)


def test_the_same_game_in_another_sitting_is_still_offered(tmp_path):
    """The reload flow is unchanged WITHIN a game; only the cross-game case is closed."""
    store = PersistentContextStore(path=tmp_path / "notes.json")
    store.load()
    store.adopt("s1", 1, None, game="civ7")
    store.record(kind="acknowledged", subject="x", turn=10, game="civ7")

    store.adopt("s2", 2, None, game="civ7")
    assert [a.session for a in store.pending] == ["s1"]


def test_an_entry_from_before_namespacing_is_offered_not_applied(tmp_path):
    """A pre-2b file records no game. It cannot be attributed, so it is shown to the
    player to accept rather than silently treated as this game's."""
    (tmp_path / "notes.json").write_text(json.dumps({
        "schema_version": SCHEMA_VERSION, "revision": 1,
        "entries": [{"id": "e1", "kind": "acknowledged", "subject": "x", "turn": 3,
                     "session": "old", "epoch": 1, "text": "", "fingerprint": "",
                     "game_key": None, "created_at": "2026-01-01T00:00:00"}]}))
    store = PersistentContextStore(path=tmp_path / "notes.json")
    store.load()
    store.adopt("s1", 1, None, game="civ7")
    assert store.of_kind("acknowledged") == ()
    assert [a.session for a in store.pending] == ["old"]


def test_a_foreign_game_s_entry_survives_a_save_made_under_this_game(tmp_path):
    """Not offering another game's entries must not mean silently erasing them: a
    later record()/save() under this game must not drop the other game's data from
    disk just because a shared --context-file happened to be adopted under a
    different game in between."""
    store = PersistentContextStore(path=tmp_path / "notes.json")
    store.load()
    store.adopt("s1", 1, None, game="civ7")
    store.record(kind="acknowledged", subject="x", turn=10, game="civ7")

    store.adopt("s2", 2, None, game="civ6")
    store.record(kind="acknowledged", subject="y", turn=1, game="civ6")  # triggers a save

    raw = json.loads((tmp_path / "notes.json").read_text())
    games = {e["game"] for e in raw["entries"]}
    assert games == {"civ7", "civ6"}

    # And switching back to civ7 offers the civ7 entry again -- it was neither lost
    # nor silently merged into civ6's own record.
    third = PersistentContextStore(path=tmp_path / "notes.json")
    third.load()
    third.adopt("s3", 3, None, game="civ7")
    assert [a.session for a in third.pending] == ["s1"]
