import civ_advisor


def test_package_has_version():
    assert civ_advisor.__version__ == "0.1.0"


def test_fixture_has_all_seven_logs(fixture_dir):
    names = sorted(p.name for p in fixture_dir.glob("*.csv"))
    assert names == [
        "AI_DiplomaticActions.csv",
        "AI_Targets.csv",
        "AI_Victories.csv",
        "Historian.csv",
        "Player_Happiness.csv",
        "Player_Stats.csv",
        "Player_Treasury.csv",
    ]
