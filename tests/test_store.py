import asyncio
from pathlib import Path

from civ7_advisor.store import Store


def test_rebuild_loads_fixture_and_ranks_insights(fixture_dir: Path):
    store = Store(fixture_dir)
    assert store.state is None and store.insights == []
    state = store.rebuild()
    assert state.latest_turn == 82 and store.state is state
    assert store.insights[0].id == "threat.at_war.4"


def test_publish_reaches_subscribers_and_unsubscribe_stops_it():
    async def scenario():
        store = Store(Path("."))
        q = store.subscribe()
        store.publish({"type": "state_changed", "turn": 5})
        assert await asyncio.wait_for(q.get(), 1) == {"type": "state_changed", "turn": 5}
        store.unsubscribe(q)
        store.publish({"type": "state_changed", "turn": 6})
        assert q.empty()

    asyncio.run(scenario())
