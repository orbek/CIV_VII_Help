"""Spec section 4.3: every number in generated prose must appear in a cited fact."""
from pathlib import Path

from civ_advisor.copilot.grounding import check, numerals_in

FACTS = [
    {"id": "gold.net.59", "value": 7, "unit": "per turn", "observed_turn": 59,
     "note": "Reserve is 152 gold."},
    {"id": "comparison.culture.59", "value": 0.44, "unit": "ratio", "observed_turn": 59,
     "note": "Your 4.4 against a rival median of 10.0."},
    {"id": "tuner.amenities.Rome.60", "value": 3, "unit": "amenities", "observed_turn": 60,
     "note": "Luxuries 1, civics 0, entertainment 2; unexplained 0."},
    {"id": "identity.human", "value": "CIVILIZATION_ROME / LEADER_TRAJAN", "unit": None,
     "observed_turn": None, "note": None},
    {"id": "gold.balance.59", "value": -12.5, "unit": "gold", "observed_turn": 59, "note": None},
    # The exact figure from the live probe that showed the conversation layer's
    # prose was NOT rounding: `t.maintenance()` on a real game answered
    # net_gold == 12.8984375 on turn 126.
    {"id": "tuner.net_gold.126", "value": 12.8984375, "unit": "per turn",
     "observed_turn": 126, "note": None},
]


def cited(*ids):
    return tuple(ids)


def test_digits_are_numerals_and_words_from_two_up_are_too():
    got = [n.text for n in numerals_in("You make 7 gold; three cities; twenty turns; one option.")]
    assert got == ["7", "three", "twenty"]


def test_the_word_one_is_not_a_numeral():
    """A pronoun in most sentences: rejecting it would reject grammar, not claims."""
    assert numerals_in("One of them is the one to build.") == ()


def test_cited_ids_are_stripped_before_scanning():
    got = numerals_in("Net gold is 7 [gold.net.59].", strip_ids=["gold.net.59"])
    assert [n.text for n in got] == ["7"]


def test_a_value_in_a_cited_fact_is_grounded():
    assert check("Your net gold is 7 per turn.", cited("gold.net.59"), FACTS).ok


def test_a_number_the_cited_facts_do_not_carry_is_rejected_and_named():
    got = check("Your net gold is 9 per turn.", cited("gold.net.59"), FACTS)
    assert not got.ok
    assert got.ungrounded == ("9",)


def test_a_number_in_an_uncited_fact_does_not_help():
    got = check("Rome has 3 amenities.", cited("gold.net.59"), FACTS)
    assert not got.ok and got.ungrounded == ("3",)


def test_the_observed_turn_of_a_cited_fact_is_grounded():
    assert check("On turn 59 you netted 7.", cited("gold.net.59"), FACTS).ok


def test_numerals_in_a_cited_note_are_grounded():
    """Notes are written by the deterministic layer from the data."""
    assert check("Your reserve is 152 gold.", cited("gold.net.59"), FACTS).ok


def test_a_ratio_may_be_written_as_a_percentage():
    assert check("You are at 44% of the median.", cited("comparison.culture.59"), FACTS).ok
    assert check("You are at 0.44 of the median.", cited("comparison.culture.59"), FACTS).ok


def test_rounding_to_the_written_precision_matches():
    assert check("Roughly 0.4 of the median.", cited("comparison.culture.59"), FACTS).ok
    assert not check("Roughly 0.45 of the median.", cited("comparison.culture.59"), FACTS).ok


def test_a_non_ratio_is_not_a_percentage():
    got = check("Amenities are at 300%.", cited("tuner.amenities.Rome.60"), FACTS)
    assert not got.ok


def test_thousands_separators_are_stripped():
    facts = FACTS + [{"id": "x", "value": 1250, "unit": "gold", "observed_turn": 59, "note": None}]
    assert check("You hold 1,250 gold.", cited("x"), facts).ok


def test_rule_3_lets_a_rounded_numeral_match_a_fact_with_more_precision():
    """Spec 4.3 rule 3. This is the tolerance that keeps rounding for DISPLAY
    (conversation.py's `_value`, and the web's `formatFactValue`) from making an
    honest generated answer fail its own validator: a model that writes "12.9"
    from a fact whose stored value is 12.8984375 must still ground, or every
    truthful rounded answer would be rejected and the copilot would silently fall
    back to deterministic prose forever."""
    assert check("Net gold is 12.9 per turn.", cited("tuner.net_gold.126"), FACTS).ok
    # A wrong rounding at the same precision is still caught: rounded to two
    # places 12.8984375 is 12.90, not 12.85 -- tolerance for PRECISION is not
    # tolerance for an invented digit.
    assert not check("Net gold is 12.85 per turn.", cited("tuner.net_gold.126"), FACTS).ok


def test_a_negative_matches_only_a_negative():
    assert check("Balance is -12.5.", cited("gold.balance.59"), FACTS).ok
    assert not check("Balance is 12.5.", cited("gold.balance.59"), FACTS).ok


def test_number_words_are_checked_like_digits():
    assert check("You have three amenities in Rome.", cited("tuner.amenities.Rome.60"), FACTS).ok
    assert not check("You have four amenities in Rome.", cited("tuner.amenities.Rome.60"), FACTS).ok


def test_an_answer_citing_nothing_may_contain_no_numbers():
    assert check("The advisor cannot see that.", (), FACTS).ok
    assert not check("It is usually about 10 turns.", (), FACTS).ok


def test_a_string_value_is_not_a_number_source():
    got = check("Trajan has 1 capital.", cited("identity.human"), FACTS)
    assert not got.ok and got.ungrounded == ("1",)


def test_a_player_reported_figure_is_admitted_when_attributed():
    facts = FACTS + [{"id": "report.turns", "kind": "player_report", "value": 8, "unit": "turns",
                      "observed_turn": 59, "note": None}]
    assert check("The 8 turns you reported on turn 59 make this the quicker option.",
                 cited("report.turns"), facts).ok


def test_a_player_reported_figure_stated_as_the_games_is_rejected():
    facts = FACTS + [{"id": "report.turns", "kind": "player_report", "value": 8, "unit": "turns",
                      "observed_turn": 59, "note": None}]
    got = check("The Granary takes 8 turns here.", cited("report.turns"), facts)
    assert not got.ok and got.unattributed == ("8",)


def test_a_figure_the_game_also_states_needs_no_attribution():
    # Grounded by a log fact as well as a report: the game did say it.
    facts = FACTS + [{"id": "report.net", "kind": "player_report", "value": 7, "unit": "per turn",
                      "observed_turn": 59, "note": None}]
    assert check("Your net gold is 7 per turn.", cited("gold.net.59", "report.net"), facts).ok


def test_a_number_the_player_just_typed_is_not_a_citation():
    """Spec 4.3 rule 7: typed into the box, it is neither dated nor stored."""
    got = check("The Granary takes 8 turns.", cited("gold.net.59"), FACTS,
                player_text="should I take the 8-turn Granary?")
    assert not got.ok and got.ungrounded == ("8",)


def test_a_typed_number_may_be_repeated_as_the_players_claim():
    facts = FACTS + [{"id": "tuner.build_option.Rome.BUILDING_GRANARY.49", "kind": "live_reading",
                      "value": 4, "unit": "turns", "observed_turn": 49, "note": None}]
    text = ("You mention 8 turns; the tuner read 4 for the Granary in Rome on turn 49. "
            "Both are reported here and neither has been corrected to the other.")
    assert check(text, cited("tuner.build_option.Rome.BUILDING_GRANARY.49"), facts,
                 player_text="should I take the 8-turn Granary?").ok


def test_a_typed_number_repeated_without_the_claim_phrase_is_rejected():
    got = check("So 8 turns it is, then, and that settles the question here.", (), FACTS,
                player_text="8 turns for the Granary")
    assert not got.ok and got.ungrounded == ("8",)


def test_a_typed_number_repeated_while_the_cited_figure_goes_unstated_is_rejected():
    """The disagreement must be NAMED: the player's 8 beside the game's 4, never 8 alone."""
    facts = FACTS + [{"id": "tuner.build_option.Rome.BUILDING_GRANARY.49", "kind": "live_reading",
                      "value": 4, "unit": "turns", "observed_turn": 49, "note": None}]
    got = check("You mention 8 turns, which is quick enough to be worth taking now.",
                cited("tuner.build_option.Rome.BUILDING_GRANARY.49"), facts,
                player_text="should I take the 8-turn Granary?")
    assert not got.ok and got.unreconciled == ("8",)


def test_the_cited_figure_stated_while_the_players_claim_is_silently_dropped_is_rejected():
    """The mirror case: neither side may be used alone. The game's 4 without the
    player's 8 quietly overrides them; the 8 without the 4 quietly adopts them."""
    facts = FACTS + [{"id": "tuner.build_option.Rome.BUILDING_GRANARY.49", "kind": "live_reading",
                      "value": 4, "unit": "turns", "observed_turn": 49, "note": None}]
    got = check("The tuner read 4 turns for the Granary in Rome on turn 49, so take it.",
                cited("tuner.build_option.Rome.BUILDING_GRANARY.49"), facts,
                player_text="should I take the 8-turn Granary?")
    assert not got.ok and got.unreconciled == ("8",)


def test_every_ungrounded_numeral_is_reported_once_in_order():
    got = check("First 9, then 9 again, then 11.", cited("gold.net.59"), FACTS)
    assert got.ungrounded == ("9", "11")


def test_a_claim_phrase_licenses_only_the_sentence_it_is_in():
    """One phrase must not cover every typed numeral in the answer. The player named
    two figures; attributing the first says nothing about the second."""
    facts = FACTS + [{"id": "tuner.build_option.Rome.BUILDING_GRANARY.49", "kind": "live_reading",
                      "value": 4, "unit": "turns", "observed_turn": 49, "note": None}]
    got = check("You mention 8 turns; the tuner read 4 for the Granary in Rome on turn 49. "
                "The Library takes 12 turns.",
                cited("tuner.build_option.Rome.BUILDING_GRANARY.49"), facts,
                player_text="is the 8-turn Granary better than the 12-turn Library?")
    assert not got.ok and got.ungrounded == ("12",)


def test_an_attribution_phrase_licenses_only_the_sentence_it_is_in():
    """The mirror for rule 6: attributing one reported figure does not attribute
    a second one stated in a later sentence as though the game said it."""
    facts = FACTS + [{"id": "report.turns", "kind": "player_report", "value": 8,
                      "unit": "turns", "observed_turn": 59, "note": None},
                     {"id": "report.cost", "kind": "player_report", "value": 240,
                      "unit": "gold", "observed_turn": 59, "note": None}]
    got = check("The 8 turns you reported on turn 59 make this the quicker option. "
                "It costs 240 gold.", cited("report.turns", "report.cost"), facts)
    assert not got.ok and got.unattributed == ("240",)


def test_a_cited_id_written_bare_in_prose_is_still_scanned():
    """Only the bracketed citation form is removed. Stripping a bare id would make the
    digits inside it vanish from the check, silently and invisibly."""
    facts = FACTS + [{"id": "guide.district.7", "value": 2, "unit": "count",
                      "observed_turn": 60, "note": None}]
    got = check("Follow guide.district.7 to the letter, in the order it gives.",
                cited("guide.district.7"), facts)
    assert not got.ok and got.ungrounded == ("7",)


# ---- provenance is not a pool of numbers -------------------------------------------

def test_a_figure_assembled_out_of_a_files_timestamp_and_digest_is_rejected():
    """Reproduced from a real ruleset fact: the mtime and the sha256 in a fact's note
    put a dozen arbitrary digits into the admitted pool, and prose could spend them on a
    payback period nothing computed. The player must read WHICH numbers were refused."""
    from civ_advisor.copilot import conversation as conv
    from civ_advisor.decisions.evidence import EvidenceLedger, ruleset_fact
    from civ_advisor.ruleset.base import RulesetFigure, RulesetIdentity

    identity = RulesetIdentity(path=Path("/games/DebugGameplay.sqlite"), size=18_051_072,
                               # 2026-09-13 14:32 UTC, and a digest whose first 12 hex
                               # characters contain 9, 3, 1, 7, 40 and 2.
                               mtime_ns=1_789_655_520_000_000_000,
                               digest="9f3a1c7b40e2" + "0" * 52)
    figure = RulesetFigure(subject="BUILDING_LIBRARY", label="Library production cost",
                           value=90, unit="production", table="Buildings", column="Cost",
                           row_key=("BUILDING_LIBRARY",), identity=identity)
    payload = conv.fact_payload(ruleset_fact(EvidenceLedger(), figure))
    text = ("The Library costs 90 production [ruleset.Buildings.BUILDING_LIBRARY.Cost]. "
            "At your current output that is about 14 turns, and it will have returned "
            "40 science by turn 32.")

    got = check(text, cited("ruleset.Buildings.BUILDING_LIBRARY.Cost"), [payload])

    assert not got.ok
    assert got.ungrounded == ("14", "40", "32")
    assert "14, 40, 32" in got.describe()


# ---- a turn in a question is not a claim about a quantity ---------------------------

def test_asking_about_a_turn_does_not_reject_a_correct_answer():
    """Rule 7 exists to stop the player's FIGURE being adopted. "on turn 130" names a
    point on the game's clock; it is not a quantity the advisor holds a rival figure for,
    and rejecting over it left the player with the fallback for every such question."""
    got = check("Your net gold is 7 per turn.", cited("gold.net.59"), FACTS,
                player_text="what should I do on turn 130?")
    assert got.ok, got.describe()


def test_a_quantity_the_player_typed_still_has_to_be_reconciled():
    """The narrowing must not reach the case rule 7 is for: a duration the player
    asserts, against a duration the tuner read."""
    facts = FACTS + [{"id": "tuner.build_option.Rome.BUILDING_GRANARY.49", "kind": "live_reading",
                      "value": 4, "unit": "turns", "observed_turn": 49, "note": None}]
    got = check("The tuner read 4 turns for the Granary in Rome on turn 49, so take it.",
                cited("tuner.build_option.Rome.BUILDING_GRANARY.49"), facts,
                player_text="should I take the 8-turn Granary?")
    assert not got.ok and got.unreconciled == ("8",)


# ---- a numeral no Decimal can compare is refused in words ---------------------------

def test_an_absurdly_precise_numeral_is_rejected_in_words_not_by_raising():
    text = f"Your net gold is {'7.' + '0' * 9000}1 per turn."
    got = check(text, cited("gold.net.59"), FACTS)
    assert not got.ok and got.ungrounded
    assert "no cited fact carries" in got.describe()


def test_a_value_written_with_absurd_but_harmless_precision_still_matches():
    assert check(f"Your net gold is {'7.' + '0' * 9000} per turn.",
                 cited("gold.net.59"), FACTS).ok
