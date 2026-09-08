from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "logs_82turns"
FIXTURE_V2_DIR = Path(__file__).parent / "fixtures" / "logs_v2"


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return FIXTURE_DIR


from civ7_advisor.ingest.load import load_logs  # noqa: E402
from civ7_advisor.state.build import build_state  # noqa: E402


@pytest.fixture(scope="session")
def fixture_state(fixture_dir: Path):
    """GameState built from the live-game fixture: latest turn 82, complete turn 81."""
    return build_state(load_logs(fixture_dir))


@pytest.fixture(scope="session")
def fixture_v2_dir() -> Path:
    if not FIXTURE_V2_DIR.is_dir():
        pytest.skip("v2 fixture not snapshotted yet (see plan Task 11)")
    return FIXTURE_V2_DIR


@pytest.fixture(scope="session")
def fixture_v2_state(fixture_v2_dir: Path):
    """GameState built from the turn-100 fixture that exercises all v2 readers."""
    return build_state(load_logs(fixture_v2_dir))
