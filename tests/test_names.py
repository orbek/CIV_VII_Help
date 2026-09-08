from civ7_advisor.state.names import NameResolver


def _resolver() -> NameResolver:
    return NameResolver.build(
        rival_names={1: "Ibn Battuta", 4: "José Rizal", 7: "Catherine"},
        human_city_keys=["LOC_CITY_NAME_MAURYA1", "LOC_CITY_NAME_MAURYA2"],
    )


def test_rival_leaders_resolve_with_or_without_accents():
    r = _resolver()
    assert r.player_for("José Rizal") == 4
    assert r.player_for("Jose Rizal") == 4
    assert r.player_for("IBN BATTUTA") == 1


def test_human_is_recognised_by_civilization_from_their_city_keys():
    r = _resolver()
    assert r.human_civ == "maurya"
    assert r.player_for("Alexander", "Maurya") == 0
    assert r.player_for("Alexander") is None  # a bare unknown leader is never guessed


def test_unknown_stays_unknown():
    assert _resolver().player_for("Napoleon", "France") is None


def test_no_human_cities_means_no_human_civ():
    r = NameResolver.build(rival_names={}, human_city_keys=[])
    assert r.human_civ is None and r.player_for("Alexander", "Maurya") is None


def test_normalize_strips_marks_case_and_spacing():
    assert NameResolver.normalize("  Trưng   Trắc ") == "trung trac"


def test_exact_gamecore_identity_resolves_human_leader_and_civilization():
    resolver = NameResolver.build(
        rival_names={}, human_city_keys=[],
        player_leaders={0: "Benjamin Franklin", 1: "Xerxes"},
        player_civilizations={0: "America", 1: "Persia"},
    )
    assert resolver.player_for("Benjamin Franklin") == 0
    assert resolver.player_for("Xerxes", "Persia") == 1
    assert resolver.player_for("Unknown", "America") == 0
