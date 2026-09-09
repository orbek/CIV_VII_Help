"""Diplomacy events in ordinary language, grouped, and honest about what it cannot read."""
from __future__ import annotations

import pytest

from civ7_advisor.advisors import diplomacy_language as language
from civ7_advisor.advisors import intel

YOU = language.Party("You", "your", second_person=True)
THEM = language.Party("Ibn Battuta", "Ibn Battuta's")


def read(action: str, details: str = "", initiator=YOU, recipient=THEM):
    return language.read(action, details, initiator, recipient)


def test_the_log_vocabulary_becomes_sentences():
    assert read("Met").text == "You and Ibn Battuta have met"
    assert read("Peace").text == "You made peace with Ibn Battuta"
    assert read("Allied").text == "You allied with Ibn Battuta"


def test_the_verb_and_the_possessive_agree_with_who_is_acting():
    assert read("At War", "Formal").text.startswith("You are at war")
    assert read("At War", "Formal", THEM, YOU).text.startswith("Ibn Battuta is at war")
    assert read("Diplomacy Action Ended", "Denounce result: Success").text.startswith("Your ")
    assert read("Diplomacy Action Ended", "Denounce result: Success",
                THEM, YOU).text.startswith("Ibn Battuta's ")


def test_the_three_kinds_of_war_stay_three_different_things():
    """A surprise war is not a formal one, and a suzerain's war is neither."""
    said = {kind: read("At War", kind).text for kind in ("Formal", "Surprise", "Suzerain War")}
    assert "after a formal declaration" in said["Formal"]
    assert "in a surprise attack" in said["Surprise"]
    assert "through a suzerain's war" in said["Suzerain War"]
    assert len(set(said.values())) == 3
    assert all(read("At War", kind).recognised for kind in said)


def test_an_unknown_war_qualifier_is_reported_rather_than_smoothed_over():
    reading = read("At War", "Ideological Crusade")
    assert "we have no words for" in reading.text
    assert "Ideological Crusade" in reading.text
    assert reading.recognised is False


def test_an_action_lifecycle_reads_as_start_progress_and_outcome():
    started = read("Diplomacy Action Started", "Cultural Exchange")
    progress = read("Diplomacy Action Support Changed",
                    "Cultural Exchange - P 1 increased support by 1")
    ended = read("Diplomacy Action Ended", "Cultural Exchange result: Success")
    cancelled = read("Diplomacy Action Ended", "Cultural Exchange result: Canceled")
    assert started.text == "You began Cultural Exchange against Ibn Battuta"
    assert started.stage == "started"
    assert progress.stage == "progress"
    assert progress.text == "Your Cultural Exchange against Ibn Battuta — increased support by 1"
    assert ended.text.endswith("finished and it succeeded")
    assert cancelled.text.endswith("finished and it was cancelled before finishing")
    # Every stage names the same action, which is what lets the feed group them.
    assert {r.action_name for r in (started, progress, ended)} == {"Cultural Exchange"}


def test_a_result_the_log_invents_is_quoted_rather_than_guessed():
    reading = read("Diplomacy Action Ended", "Denounce result: Repudiated")
    assert "the log calls 'Repudiated'" in reading.text
    assert reading.recognised is False


def test_an_unlocalised_action_key_is_read_but_flagged_as_our_reconstruction():
    reading = read("Diplomacy Action Started",
                   "LOC_DIPLOMACY_ACTION_GIVE_INFLUENCE_TOKEN_NAME")
    assert "Give Influence Token" in reading.text
    assert "the game did not supply a name for this" in reading.text
    assert reading.recognised is False


def test_a_captured_settlement_names_the_logged_key_as_a_logged_key():
    reading = read("City Capture", "LOC_CITY_NAME_MAJAPAHIT6")
    assert reading.text == ("You captured a settlement from Ibn Battuta "
                            "— logged as Majapahit6")
    assert reading.recognised is True


def test_an_action_this_module_has_never_seen_says_so_and_shows_the_log():
    reading = read("Ceremonial Insult", "with feeling")
    assert "an action this advisor has no words for" in reading.text
    assert "Ceremonial Insult — with feeling" in reading.text
    assert reading.recognised is False
    assert reading.event_type == "diplomacy.unknown"


def test_every_reading_keeps_the_logs_own_wording():
    for action, details in (("Met", ""), ("At War", "Formal"),
                            ("Diplomacy Action Ended", "Denounce result: Success"),
                            ("Nonsense", "x")):
        reading = read(action, details)
        assert action in reading.raw
        if details:
            assert details in reading.raw
