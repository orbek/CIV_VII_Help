"""Report advisor-policy metrics across every archived Civ VII session."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from civ7_advisor.advisors import economy, production, tactical, threat, victory
from civ7_advisor.ingest.load import load_logs
from civ7_advisor.state.build import build_state
from civ7_advisor.state.geo import hex_distance


def _summary(values: list[float], threshold: float | None = None, direction: str = "above") -> dict:
    ordered = sorted(values)
    def percentile(p: float) -> float | None:
        if not ordered:
            return None
        return ordered[round((len(ordered) - 1) * p)]
    out = {"n": len(ordered), "min": ordered[0] if ordered else None,
           "p50": percentile(.5), "p90": percentile(.9), "max": ordered[-1] if ordered else None}
    if threshold is not None:
        crossing = sum(v >= threshold for v in ordered) if direction == "above" else sum(v <= threshold for v in ordered)
        out |= {"threshold": threshold, "direction": direction, "crossing": crossing}
    return out


def session_dirs(root: Path) -> list[Path]:
    return sorted({p.parent for p in root.rglob("Player_Stats.csv")}) if root.is_dir() else []


def analyze(root: Path) -> dict:
    metrics: dict[str, list[float]] = {name: [] for name in (
        "war_intent", "military_ratio", "victory_output_ratio", "yield_ratio",
        "celebration_progress", "rival_military_share", "enemy_city_distance",
    )}
    sessions = []
    for path in session_dirs(root):
        state = build_state(load_logs(path))
        if not state.turns:
            continue
        sessions.append(str(path.relative_to(root)))
        for row in threat.summarize(state):
            metrics["military_ratio"].append(row.military_ratio)
            if row.war_score is not None:
                metrics["war_intent"].append(row.war_score)
        for board in victory.leaderboards(state).values():
            if len(board) > 1 and board[1][1] > 0:
                metrics["victory_output_ratio"].append(board[0][1] / board[1][1])
        metrics["yield_ratio"].extend(c.ratio for c in economy.comparison(state))
        for player in state.majors():
            row = state.at(player.id)
            if row and row.celebration_progress is not None:
                metrics["celebration_progress"].append(row.celebration_progress)
        metrics["rival_military_share"].extend(production.rival_military_share(state).values())
        cities = tactical.human_city_tiles(state)
        for unit in tactical.enemy_units(state):
            if cities:
                metrics["enemy_city_distance"].append(min(hex_distance((unit.x, unit.y), c) for c in cities))
    thresholds = {
        "war_intent": threat.WAR_INTENT_WARN, "military_ratio": threat.MILITARY_RATIO_ADVISE,
        "victory_output_ratio": victory.LEAD_MARGIN, "yield_ratio": economy.BEHIND_RATIO,
        "celebration_progress": economy.CELEBRATION_NEAR,
        "rival_military_share": production.RIVAL_MILITARY_SHARE,
        "enemy_city_distance": tactical.NEAR_TILES,
    }
    below = {"yield_ratio", "enemy_city_distance"}
    return {"archive_root": str(root), "session_count": len(sessions), "sessions": sessions,
            "metrics": {name: _summary(values, thresholds[name], "below" if name in below else "above")
                        for name, values in metrics.items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, default=Path.home() / ".civ7-advisor/archive")
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    args = parser.parse_args(argv)
    report = analyze(args.archive_dir)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
