"""Whether the tuner is enabled is READ from AppOptions.txt, never inferred from a
refused connection. Confirmed live on 2026-09-13: with EnableTuner 1 set, connections
are still refused while the game sits at the main menu."""
from pathlib import Path

import pytest

from civ_advisor.tuner.base import TunerUnavailable
from civ_advisor.tuner.client import open_tuner
from civ_advisor.tuner.options import TunerFlag, read_enable_tuner

REAL_SHAPE = """[Video]
RenderWidth 1920

[Debug]
;Enable FireTuner.
EnableTuner {value}

;Enable the debug menu.
EnableDebugMenu 1

[Misc]
EnableTuner 1
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "AppOptions.txt"
    path.write_text(text)
    return path


def test_the_flag_on_is_read_from_the_debug_section(tmp_path):
    flag, detail = read_enable_tuner(write(tmp_path, REAL_SHAPE.format(value=1)))
    assert flag is TunerFlag.ON
    assert "EnableTuner 1" in detail


def test_the_flag_off_is_read_from_the_debug_section(tmp_path):
    assert read_enable_tuner(write(tmp_path, REAL_SHAPE.format(value=0)))[0] is TunerFlag.OFF


def test_a_line_outside_debug_does_not_count(tmp_path):
    """The [Misc] copy above says 1; only [Debug] governs the tuner."""
    text = REAL_SHAPE.format(value=0)
    assert read_enable_tuner(write(tmp_path, text))[0] is TunerFlag.OFF


def test_no_line_at_all_is_off(tmp_path):
    flag, detail = read_enable_tuner(write(tmp_path, "[Debug]\nEnableDebugMenu 1\n"))
    assert flag is TunerFlag.OFF and "no EnableTuner line" in detail


def test_a_commented_out_line_is_off(tmp_path):
    assert read_enable_tuner(write(tmp_path, "[Debug]\n;EnableTuner 1\n"))[0] is TunerFlag.OFF


def test_a_trailing_comment_does_not_turn_the_flag_off(tmp_path):
    """`EnableTuner 1 ;on` is the flag SET. Reading it as off is §4.6's own defect: the
    player is told to set something they have already set."""
    flag, detail = read_enable_tuner(
        write(tmp_path, "[Debug]\nEnableTuner 1   ;Enable FireTuner.\n"))
    assert flag is TunerFlag.ON
    assert "EnableTuner 1" in detail and "FireTuner" not in detail


def test_a_trailing_comment_on_an_off_flag_still_reads_off(tmp_path):
    flag, detail = read_enable_tuner(write(tmp_path, "[Debug]\nEnableTuner 0 ;off\n"))
    assert flag is TunerFlag.OFF and "EnableTuner 0" in detail


def test_a_trailing_comment_on_the_section_header_is_still_the_debug_section(tmp_path):
    flag, _ = read_enable_tuner(write(tmp_path, "[Debug] ;debug options\nEnableTuner 1\n"))
    assert flag is TunerFlag.ON


def test_a_refusal_with_a_commented_flag_on_never_says_to_change_it(tmp_path):
    """What the player actually sees: the sentence must not tell them to set a flag the
    file already sets."""
    t = open_tuner(port=1, timeout=0.5,
                   app_options=write(tmp_path, "[Debug]\nEnableTuner 1 ;Enable FireTuner.\n"))
    assert t.unavailable is TunerUnavailable.NOT_ANSWERING
    assert "Set `EnableTuner 1`" not in t.reason


def test_an_absent_file_is_unreadable_and_names_the_path(tmp_path):
    flag, detail = read_enable_tuner(tmp_path / "nowhere" / "AppOptions.txt")
    assert flag is TunerFlag.UNREADABLE and "nowhere" in detail


def test_the_file_is_opened_read_only_and_left_untouched(tmp_path):
    path = write(tmp_path, REAL_SHAPE.format(value=1))
    before = (path.stat().st_mtime_ns, path.read_bytes())
    read_enable_tuner(path)
    assert (path.stat().st_mtime_ns, path.read_bytes()) == before


def test_a_refusal_with_the_flag_off_is_not_enabled_and_says_what_to_change(tmp_path):
    t = open_tuner(port=1, timeout=0.5, app_options=write(tmp_path, REAL_SHAPE.format(value=0)))
    assert t.unavailable is TunerUnavailable.NOT_ENABLED
    assert "EnableTuner 1" in t.reason


def test_a_refusal_with_the_flag_on_is_not_answering_and_never_says_to_change_it(tmp_path):
    t = open_tuner(port=1, timeout=0.5, app_options=write(tmp_path, REAL_SHAPE.format(value=1)))
    assert t.unavailable is TunerUnavailable.NOT_ANSWERING
    assert "main menu" in t.reason
    assert "Set `EnableTuner 1`" not in t.reason


def test_a_refusal_with_no_readable_file_is_unestablished(tmp_path):
    t = open_tuner(port=1, timeout=0.5, app_options=tmp_path / "missing.txt")
    assert t.unavailable is TunerUnavailable.UNESTABLISHED
    assert "could not be read" in t.reason and "missing.txt" in t.reason


def test_the_six_absences_are_distinct():
    assert len(set(TunerUnavailable)) == 6
