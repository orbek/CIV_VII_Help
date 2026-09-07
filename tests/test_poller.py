import asyncio
from pathlib import Path

from civ7_advisor.ingest.poller import snapshot, watch


def test_snapshot_reports_missing_files_as_none(tmp_path: Path):
    (tmp_path / "a.csv").write_text("1\n")
    snap = snapshot(tmp_path, ["a.csv", "b.csv"])
    assert snap["b.csv"] is None
    assert snap["a.csv"][1] == 2  # size in bytes


def test_watch_fires_once_after_a_quiet_interval(tmp_path: Path):
    f = tmp_path / "a.csv"
    f.write_text("1\n")
    calls: list[int] = []

    async def scenario():
        task = asyncio.create_task(watch(tmp_path, ["a.csv"], lambda: calls.append(1), interval=0.02))
        await asyncio.sleep(0.1)
        assert calls == []  # nothing changed
        f.write_text("1\n2\n")
        await asyncio.sleep(0.15)
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
