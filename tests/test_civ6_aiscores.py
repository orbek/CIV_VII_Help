import pytest

from civ_advisor.ingest.aiscores import (
    DiplomacyModifierRow, MilitaryRow, read_diplomacy_modifiers, read_military,
)
from civ_advisor.ingest.csvfile import LogFormatError


def test_military_parses_the_capture(civ6_dir):
    rows = read_military(civ6_dir / "AI_Military.csv")

    assert len(rows) == 833
    assert max(r.turn for r in rows) == 53
    last = [r for r in rows if r.turn == 53]
    assert last == [MilitaryRow(
        turn=53, player=0, regional_strength=65, enemy_strength=135,
        other_strength=20, fav_tech="TECH_ARCHERY", combat_desire=3.5,
    )]


def test_military_reads_combat_desire_for_every_major_on_a_full_turn(civ6_dir):
    rows = read_military(civ6_dir / "AI_Military.csv")
    turn52 = {r.player: r.combat_desire for r in rows if r.turn == 52}

    assert turn52[0] == 4.8
    assert turn52[2] == 1.0
    assert turn52[4] == 0.3


def test_military_rejects_a_changed_header(tmp_path):
    path = tmp_path / "AI_Military.csv"
    path.write_text("Game Turn, Player, Combat Desire\n1, 0, 2.0\n", encoding="utf-8")
    with pytest.raises(LogFormatError, match="AI_Military.csv"):
        read_military(path)


def test_military_reads_only_the_latest_game(tmp_path):
    """Civ VI never truncates this log: without segmenting, a previous match's
    combat desire would be read as this match's."""
    path = tmp_path / "AI_Military.csv"
    header = ("Game Turn, Player, Regional Strength, Enemy Strength, Other Strength, "
              "Current Explorers, Desired Explorers, Fav Tech, Combat Desire\n")
    path.write_text(
        header
        + "80, 0, 10, 10, 10, 1:0, 1:1, TECH_ARCHERY, 99.0\n"
        + "1, 0, 20, 20, 20, 1:0, 1:1, TECH_MINING, 1.0\n"
        + "2, 0, 20, 20, 20, 1:0, 1:1, TECH_MINING, 2.0\n",
        encoding="utf-8",
    )
    rows = read_military(path)

    assert [r.turn for r in rows] == [1, 2]
    assert 99.0 not in [r.combat_desire for r in rows]


def test_modifiers_parse_all_three_row_widths(civ6_dir):
    """Activate rows carry 11 columns, Update 6, Deactivate 5. All three are the
    file's real format; a reader that demanded 11 would drop two thirds of it."""
    rows = read_diplomacy_modifiers(civ6_dir / "DiplomacyModifiers.csv")

    assert len(rows) == 22
    assert {r.action for r in rows} == {"Activate", "Update", "Deactivate"}
    activate = [r for r in rows if r.action == "Activate"]
    update = [r for r in rows if r.action == "Update"]
    deactivate = [r for r in rows if r.action == "Deactivate"]
    assert len(activate) == 12 and len(update) == 6 and len(deactivate) == 4
    assert all(r.value is not None and r.reduction is not None for r in activate)
    assert all(r.value is not None and r.max_value is None for r in update)
    assert all(r.value is None for r in deactivate)


def test_modifiers_keep_the_games_own_wording(civ6_dir):
    rows = read_diplomacy_modifiers(civ6_dir / "DiplomacyModifiers.csv")
    worst = min((r for r in rows if r.value is not None), key=lambda r: r.value)

    assert worst == DiplomacyModifierRow(
        turn=50, player=5, opponent=0,
        modifier="Likes civs who respect the environment", action="Activate",
        value=-8.0, max_value=-8.0, accum_amount=1.0, accum_turns=0,
        cooldown_turns=0, reduction=1.0,
    )


def test_modifiers_raise_on_a_width_the_file_never_has(tmp_path):
    """Admitting 11/6/5 is not the same as admitting anything: an unrecognised
    width is a format change, and quietly dropping it would be data loss."""
    path = tmp_path / "DiplomacyModifiers.csv"
    path.write_text(
        "Game Turn, Player, Opponent, Modifier, Change, Value, Max, Accum Amt, "
        "Accum Turns, Cooldown Turns, Reduction\n"
        "12, 0, 5, First impressions of you, Activate, 2.0, 2.0\n",
        encoding="utf-8",
    )
    with pytest.raises(LogFormatError, match="7"):
        read_diplomacy_modifiers(path)
