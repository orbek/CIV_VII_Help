import os
import time
from pathlib import Path

import pytest

from civ_advisor.games.civ6 import CIV6
from civ_advisor.games.civ7 import CIV7
from civ_advisor.games.detect import ALL_STALE, DETECTED, NO_CANDIDATES
from civ_advisor.games.registry import UnknownGame
from civ_advisor.games.selection import AUTO, PINNED, GameSelector


def _live(logs_dir: Path, name: str, age_s: float = 2) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / name).write_text("x")
    when = time.time() - age_s
    os.utime(logs_dir / name, (when, when))


@pytest.fixture
def dirs(tmp_path):
    return {"civ7": tmp_path / "civ7", "civ6": tmp_path / "civ6"}


def test_auto_follows_detection(dirs):
    _live(dirs["civ6"], "Player_Stats.csv")
    resolved = GameSelector(logs_dirs=dirs).resolve()
    assert resolved.mode == AUTO
    assert resolved.profile is CIV6 and resolved.detected_id == "civ6"
    assert resolved.disagrees is False


def test_a_pin_wins_over_detection_and_says_that_it_disagrees(dirs):
    _live(dirs["civ6"], "Player_Stats.csv")
    resolved = GameSelector(pinned="civ7", logs_dirs=dirs).resolve()
    assert resolved.mode == PINNED
    assert resolved.profile is CIV7
    assert resolved.detected_id == "civ6"
    assert resolved.disagrees is True


def test_a_pin_that_agrees_does_not_claim_a_disagreement(dirs):
    _live(dirs["civ6"], "Player_Stats.csv")
    resolved = GameSelector(pinned="civ6", logs_dirs=dirs).resolve()
    assert resolved.detected_id == "civ6" and resolved.disagrees is False


def test_a_pin_with_no_detection_is_not_a_disagreement(dirs):
    """Detection saying "I cannot tell" does not contradict the pin. Reporting it as a
    disagreement would train the player to ignore a warning that means something."""
    resolved = GameSelector(pinned="civ7", logs_dirs=dirs).resolve()
    assert resolved.detection_reason in {NO_CANDIDATES, ALL_STALE}
    assert resolved.detected_id is None and resolved.disagrees is False
    assert resolved.profile is CIV7      # a pin still resolves with nothing on disk


def test_auto_with_nothing_recent_resolves_to_no_game(dirs):
    resolved = GameSelector(logs_dirs=dirs).resolve()
    assert resolved.profile is None and resolved.logs_dir is None
    assert resolved.mode == AUTO


def test_pinning_and_unpinning_switch_the_mode(dirs):
    _live(dirs["civ6"], "Player_Stats.csv")
    selector = GameSelector(logs_dirs=dirs)
    assert selector.mode == AUTO
    selector.pin("civ7")
    assert selector.mode == PINNED and selector.resolve().profile is CIV7
    selector.unpin()
    assert selector.mode == AUTO and selector.resolve().profile is CIV6


def test_pinning_an_unknown_game_is_refused(dirs):
    selector = GameSelector(logs_dirs=dirs)
    with pytest.raises(UnknownGame):
        selector.pin("civ5")
    assert selector.mode == AUTO      # the refused pin left no trace


def test_an_overridden_logs_dir_reaches_the_resolution(dirs, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    _live(elsewhere, "Player_Stats.csv")
    resolved = GameSelector(pinned="civ7", logs_dirs={"civ7": elsewhere}).resolve()
    assert resolved.logs_dir == elsewhere


def test_a_disagreeing_pin_does_not_decay_across_repeated_resolves(dirs):
    """A pin holds for the session until the player changes it. Detection disagreeing
    must never itself un-pin -- that would silently move a player off a game they
    deliberately chose."""
    _live(dirs["civ6"], "Player_Stats.csv")
    selector = GameSelector(pinned="civ7", logs_dirs=dirs)
    for _ in range(3):
        resolved = selector.resolve()
        assert selector.mode == PINNED
        assert resolved.profile is CIV7 and resolved.pinned_id == "civ7"
        assert resolved.disagrees is True
