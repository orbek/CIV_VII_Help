import asyncio
import logging
from pathlib import Path

from civ_advisor.ingest.poller import snapshot, watch


def test_snapshot_reports_missing_files_as_none(tmp_path: Path):
    (tmp_path / "a.csv").write_text("1\n")
    snap = snapshot(tmp_path, ["a.csv", "b.csv"])
    assert snap["b.csv"] is None
    assert snap["a.csv"][1] == 2  # size in bytes


def test_watch_fires_once_after_a_quiet_interval(tmp_path: Path):
    interval = 0.1  # long enough that the assertions below get a comfortable margin
    f = tmp_path / "a.csv"
    f.write_text("1\n")
    calls: list[int] = []

    async def scenario():
        task = asyncio.create_task(
            watch(tmp_path, ["a.csv"], lambda: calls.append(1), interval=interval)
        )
        await asyncio.sleep(interval * 1.7)
        assert calls == []  # nothing changed
        f.write_text("1\n2\n")  # the poll ~0.3 intervals from now observes this
        await asyncio.sleep(interval * 0.8)  # still under one interval since the write
        assert calls == []  # observing a change must not fire on its own
        await asyncio.sleep(interval * 3)  # now well past the quiet period
        assert calls == [1]  # changed, then quiet -> exactly one rebuild
        task.cancel()

    asyncio.run(scenario())


def test_watch_waits_while_files_keep_changing(tmp_path: Path):
    f = tmp_path / "a.csv"
    f.write_text("1\n")
    calls: list[int] = []

    async def scenario():
        task = asyncio.create_task(watch(tmp_path, ["a.csv"], lambda: calls.append(1), interval=0.03))
        for i in range(5):  # keep writing faster than the interval
            f.write_text("1\n" * (i + 2))
            await asyncio.sleep(0.01)
        assert calls == []
        await asyncio.sleep(0.12)
        assert calls == [1]
        task.cancel()

    asyncio.run(scenario())


def test_watch_survives_a_failing_on_change(tmp_path: Path, caplog):
    """A rebuild that raises must be logged, not end the watcher for the session."""
    f = tmp_path / "a.csv"
    f.write_text("1\n")
    calls: list[int] = []

    def on_change() -> None:
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise RuntimeError("rebuild exploded")

    async def scenario():
        task = asyncio.create_task(watch(tmp_path, ["a.csv"], on_change, interval=0.02))
        await asyncio.sleep(0.05)  # let the watcher take its baseline snapshot
        f.write_text("1\n2\n")
        await asyncio.sleep(0.15)
        assert calls == [1]  # the first rebuild raised
        assert not task.done()  # ... and the watcher is still polling
        f.write_text("1\n2\n3\n")
        await asyncio.sleep(0.15)
        assert calls == [1, 2]  # a later change still gets rebuilt
        task.cancel()

    with caplog.at_level(logging.ERROR, logger="civ_advisor.ingest.poller"):
        asyncio.run(scenario())
    assert "poll failed; continuing" in caplog.text  # the failure was not silent


def test_watch_skips_the_rebuild_for_an_up_to_date_initial(tmp_path: Path):
    f = tmp_path / "a.csv"
    f.write_text("1\n")
    calls: list[int] = []

    async def scenario():
        current = snapshot(tmp_path, ["a.csv"])  # what the caller has already loaded
        task = asyncio.create_task(
            watch(tmp_path, ["a.csv"], lambda: calls.append(1), interval=0.02, initial=current)
        )
        await asyncio.sleep(0.15)
        assert calls == []  # nothing has changed since the caller's snapshot
        task.cancel()

    asyncio.run(scenario())


def test_watch_rebuilds_when_initial_is_stale(tmp_path: Path):
    f = tmp_path / "a.csv"
    f.write_text("1\n")
    stale = snapshot(tmp_path, ["a.csv"])
    f.write_text("1\n2\n")  # written after the caller took its snapshot
    calls: list[int] = []

    async def scenario():
        task = asyncio.create_task(
            watch(tmp_path, ["a.csv"], lambda: calls.append(1), interval=0.02, initial=stale)
        )
        await asyncio.sleep(0.15)
        assert calls == [1]  # the missed change is picked up
        task.cancel()

    asyncio.run(scenario())
