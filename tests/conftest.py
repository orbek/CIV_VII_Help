from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "logs_82turns"


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return FIXTURE_DIR
