from dataclasses import replace
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "logs_82turns"
FIXTURE_V2_DIR = Path(__file__).parent / "fixtures" / "logs_v2"
FIXTURE_CIV6_DIR = Path(__file__).parent / "fixtures" / "logs_civ6"


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return FIXTURE_DIR


from civ_advisor.games.civ7 import CIV7  # noqa: E402
from civ_advisor.ingest.load import load_logs  # noqa: E402
from civ_advisor.state.build import build_state  # noqa: E402


@pytest.fixture(scope="session")
def fixture_state(fixture_dir: Path):
    """GameState built from the live-game fixture: latest turn 82, complete turn 81."""
    return build_state(load_logs(fixture_dir, profile=CIV7))


@pytest.fixture(scope="session")
def fixture_v2_dir() -> Path:
    if not FIXTURE_V2_DIR.is_dir():
        pytest.skip("v2 fixture not snapshotted yet (see plan Task 11)")
    return FIXTURE_V2_DIR


@pytest.fixture(scope="session")
def fixture_v2_state(fixture_v2_dir: Path):
    """GameState built from the turn-100 fixture that exercises all v2 readers."""
    return build_state(load_logs(fixture_v2_dir, profile=CIV7))


@pytest.fixture(scope="session")
def civ6_dir() -> Path:
    if not FIXTURE_CIV6_DIR.is_dir():
        pytest.skip("civ6 fixture not installed")
    return FIXTURE_CIV6_DIR


from civ_advisor.games.base import GameProfile
from civ_advisor.games.civ6 import CIV6
from civ_advisor.tuner.client import open_tuner  # noqa: E402
from civ_advisor.store import Store  # noqa: E402


def unreachable_tuner(profile: GameProfile) -> GameProfile:
    """The same profile, with its tuner pointed somewhere nothing can listen.

    Without this a test's result depends on whether the developer happens to have
    Civilization VI open: the real CIV6 profile dials 127.0.0.1:4318, so a running
    game turns "the socket is closed" tests into "the socket answered" ones. Port 1
    is reserved and cannot be bound, so the refusal is a property of the test rather
    than of the machine it runs on.
    """
    return replace(profile, tuner=lambda: open_tuner(port=1, timeout=0.2))


@pytest.fixture
def civ6_store(civ6_dir: Path) -> Store:
    return Store(civ6_dir, profile=unreachable_tuner(CIV6))


@pytest.fixture
def civ7_store(fixture_dir: Path) -> Store:
    return Store(fixture_dir, profile=CIV7)


from civ_advisor.games import registry  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_registry_state():
    """Snapshot and restore the registry's mutable state before and after each test.

    Tests register profiles into the global _PROFILES dict, which would persist
    across test files in a single pytest run and cause cross-test contamination.
    This fixture ensures each test starts with a clean registry state while preserving
    any production profiles, which register at import time (before any test runs) and
    so are already present in the snapshot; only ids a test registers itself are wiped.
    """
    # Snapshot the current state before the test
    snapshot = registry._PROFILES.copy()

    yield

    # Restore the snapshot after the test
    registry._PROFILES.clear()
    registry._PROFILES.update(snapshot)
