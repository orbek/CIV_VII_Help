from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "logs_82turns"


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return FIXTURE_DIR


from civ7_advisor.ingest.load import load_logs  # noqa: E402
from civ7_advisor.state.build import build_state  # noqa: E402


@pytest.fixture(scope="session")
def fixture_state(fixture_dir: Path):
    """GameState built from the live-game fixture: latest turn 82, complete turn 81."""
    return build_state(load_logs(fixture_dir))
