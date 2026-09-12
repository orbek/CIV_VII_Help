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


def test_tech_scores_parse_the_trimmed_capture(civ6_dir):
    """The committed AI_Research.csv is trimmed to 400 lines, which covers
    turns 1-2 only. Nothing may assume it reaches complete_through_turn."""
    from civ_advisor.ingest.aiscores import read_tech_scores

    rows = read_tech_scores(civ6_dir / "AI_Research.csv")

    assert len(rows) == 399
    assert sorted({r.turn for r in rows}) == [1, 2]
    assert {r.action for r in rows} == {"Tech"}


def test_tech_scores_carry_the_ais_stated_goal(civ6_dir):
    """`Boost` == GOAL is the AI saying which tech it selected -- a statement,
    not an inference. Exactly one such row per player per turn, where it has one."""
    from civ_advisor.ingest.aiscores import GOAL, read_tech_scores

    rows = read_tech_scores(civ6_dir / "AI_Research.csv")
    goals = [r for r in rows if r.boost == GOAL]

    assert all(r.tech == "TECH_WRITING" for r in goals)
    per_player_turn = [(r.turn, r.player) for r in goals]
    assert len(per_player_turn) == len(set(per_player_turn))
    cyrus = next(r for r in goals if r.turn == 2 and r.player == 2)
    assert cyrus.score == 400.1


def test_tech_score_boost_is_none_when_the_column_is_blank(civ6_dir):
    """352 of the fixture's 399 rows have an empty Boost cell. Empty means the
    AI said nothing about that tech, which is not the same as GOAL or OWNED."""
    from civ_advisor.ingest.aiscores import read_tech_scores

    rows = read_tech_scores(civ6_dir / "AI_Research.csv")

    assert sum(r.boost is None for r in rows) == 352
    assert {r.boost for r in rows if r.boost} == {"GOAL", "OWNED", "RESEARCHING"}


def test_policy_scores_parse_both_row_widths(civ6_dir):
    """Civic rows carry 6 columns, Policies rows 5 -- the Turns column is absent
    on a policy card, and is left None rather than zeroed."""
    from civ_advisor.ingest.aiscores import read_policy_scores

    rows = read_policy_scores(civ6_dir / "AI_GovtPolicies.csv")

    assert len(rows) == 399
    assert sorted({r.turn for r in rows}) == [1, 2, 3]
    civics = [r for r in rows if r.action == "Civic"]
    policies = [r for r in rows if r.action == "Policies"]
    assert len(civics) == 295 and len(policies) == 104
    assert all(r.turns is not None for r in civics)
    assert all(r.turns is None for r in policies)


def test_policy_scores_keep_the_games_own_keys(civ6_dir):
    from civ_advisor.ingest.aiscores import PolicyScoreRow, read_policy_scores

    rows = read_policy_scores(civ6_dir / "AI_GovtPolicies.csv")
    cyrus = [r for r in rows if r.turn == 1 and r.player == 2]

    assert cyrus[0] == PolicyScoreRow(
        turn=1, player=2, action="Civic", policy="CIVIC_CODE_OF_LAWS",
        score=145.2, turns=20,
    )
    assert max(cyrus, key=lambda r: r.score).score == 204.9


def test_policy_scores_read_only_the_latest_game(tmp_path):
    from civ_advisor.ingest.aiscores import read_policy_scores

    path = tmp_path / "AI_GovtPolicies.csv"
    path.write_text(
        "Game Turn, Player, Action, Policy, Score, Turns\n"
        "90, 0, Civic, CIVIC_MYSTICISM, 999.0, 3\n"
        "1, 0, Civic, CIVIC_CODE_OF_LAWS, 10.0, 20\n",
        encoding="utf-8",
    )
    rows = read_policy_scores(path)

    assert [r.turn for r in rows] == [1]


def test_tech_scores_reject_a_changed_header(tmp_path):
    from civ_advisor.ingest.aiscores import read_tech_scores

    path = tmp_path / "AI_Research.csv"
    path.write_text("Game Turn, Player, Tech, Score\n1, 0, TECH_MINING, 5.0\n",
                    encoding="utf-8")
    with pytest.raises(LogFormatError, match="AI_Research.csv"):
        read_tech_scores(path)
