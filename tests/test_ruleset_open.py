import threading
import time

import pytest

from civ_advisor.ruleset.civ6 import Civ6Ruleset, clear_cache, open_ruleset

from tests.ruleset_fixture import SCHEMA, make_ruleset


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_a_missing_database_degrades_to_asking_the_player(tmp_path):
    provider = open_ruleset(tmp_path / "nothing-here.sqlite")

    assert provider.available is False
    assert provider.building("BUILDING_LIBRARY") is None
    assert "nothing-here.sqlite" in provider.reason
    assert "preview" in provider.reason


def test_a_file_that_is_not_a_database_degrades(tmp_path):
    path = tmp_path / "DebugGameplay.sqlite"
    path.write_bytes(b"this is not a database")

    provider = open_ruleset(path)

    assert provider.available is False
    assert "could not be read" in provider.reason


def test_a_changed_schema_degrades_and_names_what_is_missing(tmp_path):
    """A patch that renames a column must stop the advisor quoting figures, not make it
    quote the wrong ones."""
    renamed = SCHEMA.replace("Cost INTEGER", "ProductionCost INTEGER")
    path = make_ruleset(tmp_path, schema=renamed, rows={"Buildings": []})

    provider = open_ruleset(path)

    assert provider.available is False
    assert "Buildings" in provider.reason and "Cost" in provider.reason


def test_a_missing_table_degrades(tmp_path):
    without_yields = "".join(
        f"{statement};" for statement in SCHEMA.split(";")
        if statement.strip() and "Building_YieldChanges" not in statement)
    path = make_ruleset(tmp_path, schema=without_yields,
                        rows={"Building_YieldChanges": []})

    provider = open_ruleset(path)

    assert provider.available is False
    assert "Building_YieldChanges" in provider.reason


def test_the_same_unchanged_file_is_opened_once(tmp_path):
    path = make_ruleset(tmp_path)

    assert open_ruleset(path) is open_ruleset(path)


def test_a_modded_ruleset_is_re_derived_rather_than_served_stale(tmp_path):
    """The reason the cache is keyed on the file and not on the path. A stale cost is
    worse than no cost: it is indistinguishable from a verified one."""
    path = make_ruleset(tmp_path)
    assert open_ruleset(path).building("BUILDING_LIBRARY").cost.value == 90

    path.unlink()
    make_ruleset(tmp_path, rows={"Buildings": [
        ("BUILDING_LIBRARY", "LOC_X", 45, 1, "DISTRICT_CAMPUS", "TECH_WRITING", "", 0, 0,
         0, None, 0)]})

    provider = open_ruleset(path)
    assert provider.building("BUILDING_LIBRARY").cost.value == 45
    assert isinstance(provider, Civ6Ruleset)


def test_a_provider_closed_out_from_under_a_caller_degrades_instead_of_raising(tmp_path):
    """Important #1 from review: `clear_cache()` closes every cached provider for a
    game switch, but a caller may still be holding a reference from before that -- a
    rebuild that was already mid-flight. A closed provider must behave like any other
    degraded one, not raise sqlite3.ProgrammingError into the advisor.

    Queries a building NOT already cached by this provider after the close, so the
    lookup cannot be answered from `_cache` alone and must actually reach (or refuse to
    reach) the closed connection -- otherwise this would pass even if the closed check
    were missing entirely."""
    path = make_ruleset(tmp_path)
    provider = open_ruleset(path)
    assert provider.building("BUILDING_LIBRARY") is not None

    clear_cache()

    assert provider.available is False
    assert "closed" in provider.reason.lower()
    assert provider.building("BUILDING_BANK") is None


def test_reopening_after_a_close_gets_a_fresh_working_provider(tmp_path):
    """The degraded state belongs to the specific reference that was closed, not to the
    path forever -- the next `open_ruleset` call for the same file must work normally."""
    path = make_ruleset(tmp_path)
    open_ruleset(path)
    clear_cache()

    reopened = open_ruleset(path)

    assert reopened.available is True
    assert reopened.building("BUILDING_LIBRARY").cost.value == 90


def test_concurrent_opens_of_different_paths_do_not_serialize_behind_each_others_io(
    tmp_path, monkeypatch,
):
    """Important #2 from review: `_LOCK` must guard only `_OPEN`, not the file work.
    Opening path A must not block a concurrent caller opening a different path B."""
    path_a = make_ruleset(tmp_path / "a", name="DebugGameplay.sqlite")
    path_b = make_ruleset(tmp_path / "b", name="DebugGameplay.sqlite")
    original_open = Civ6Ruleset.open.__func__

    def slow_open(cls, p):
        time.sleep(0.15)
        return original_open(cls, p)

    monkeypatch.setattr(Civ6Ruleset, "open", classmethod(slow_open))

    started = time.monotonic()
    threads = [threading.Thread(target=open_ruleset, args=(p,)) for p in (path_a, path_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - started

    # Serialized behind one global lock this would take >= 0.30s; run concurrently it
    # should take close to one open's own duration.
    assert elapsed < 0.25


def test_two_threads_racing_to_open_the_same_new_path_keep_only_one_connection(
    tmp_path, monkeypatch,
):
    """Important #2's other half: the recheck-after-unlocked-IO that stops two threads
    which both missed the cache from publishing two different providers for the same
    path. The loser's connection must be closed, not leaked -- checked here through
    Important #1's own `.available`, proving the two fixes compose correctly."""
    path = make_ruleset(tmp_path)
    original_open = Civ6Ruleset.open.__func__
    opened: list[Civ6Ruleset] = []
    barrier = threading.Barrier(2)

    def synchronized_open(cls, p):
        barrier.wait()  # hold both threads here until both have missed the cache
        provider = original_open(cls, p)
        opened.append(provider)
        return provider

    monkeypatch.setattr(Civ6Ruleset, "open", classmethod(synchronized_open))

    results: list = [None, None]

    def run(i: int) -> None:
        results[i] = open_ruleset(path)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(opened) == 2               # both threads actually did their own IO
    assert results[0] is results[1]       # only one of the two was published
    winner = results[0]
    loser = opened[1] if opened[0] is winner else opened[0]
    assert winner.available is True
    assert loser.available is False       # the surplus connection was closed, not leaked
