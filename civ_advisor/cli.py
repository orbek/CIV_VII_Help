"""`civ-advisor` / `civ7-advisor` commands: start the dashboard server, or inspect
the log archive. Both run `main()`; only their default `--game` differs."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import uvicorn

from civ_advisor.api.app import create_app
from civ_advisor.archive import DEFAULT_ROOT, LEGACY_ARCHIVE_ROOT, MANIFEST, archive_root_for
from civ_advisor.context_store import (
    DEFAULT_STORE_PATH, LEGACY_STORE_PATH, PersistentContextStore, store_path_for,
)
from civ_advisor.copilot import CopilotWorker
from civ_advisor.games.civ7 import CIV7
from civ_advisor.games.registry import UnknownGame, get_profile, profile_ids
from civ_advisor.games.selection import AUTO, GameSelector
from civ_advisor.llm import DEFAULT_MODEL, CommentaryWorker, OllamaClient
from civ_advisor.llm.client import DEFAULT_TIMEOUT_S

DEFAULT_LOGS_DIR = CIV7.default_logs_dir  # retained: the path Civ VII users know

# `civ7-advisor` is Phase 1's console script, kept as an alias so a Civ VII-only
# invocation never changes: it still defaults to a fixed civ7. The new `civ-advisor`
# name defaults to `auto` instead, because once a second game is registered a `civ7`
# default makes detection invisible. Both scripts point at the same `main`, so the two
# defaults are told apart by argv[0] alone -- and anything else (a test harness, `python
# -m civ_advisor.cli`, a frozen build) falls back to `auto`, the answer that never
# silently ignores a Civ VI player.
LEGACY_ENTRY_POINT = "civ7-advisor"


def _default_game() -> str:
    return "civ7" if Path(sys.argv[0]).name == LEGACY_ENTRY_POINT else AUTO


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["archive"]:
        return _archive_command(argv[1:])

    default_game = _default_game()
    parser = argparse.ArgumentParser(
        prog="civ-advisor",
        description="Second-screen turn advisor for Civilization VI and VII. Reads the game's "
                    f"own log files; never writes to them. Archives them under {DEFAULT_ROOT} "
                    "(per game) because Civ VII deletes its logs on launch.",
    )
    parser.add_argument("--game", default=None,
                        help="which game to advise on, or 'auto' to detect it each poll: "
                             f"{', '.join(profile_ids())}, {AUTO} "
                             f"(default: {default_game}; required with --logs-dir)")
    parser.add_argument("--logs-dir", type=Path, default=None,
                        help="log directory to read (default: the chosen game's own)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--poll-interval", type=float, default=1.0,
                        help="seconds between checks of the log files (default 1.0)")
    parser.add_argument("--archive-dir", type=Path, default=None,
                        help="a single destination every game's logs are mirrored into "
                             "directly, with no per-game subfolder -- NOT the same meaning "
                             "as 'archive list's own --archive-dir, which names the base "
                             f"holding every game's own archive (default: {DEFAULT_ROOT}/<game>/archive)")
    parser.add_argument("--no-archive", action="store_true", help="do not mirror the logs anywhere")
    parser.add_argument("--llm-model", default=DEFAULT_MODEL,
                        help=f"local Ollama model for commentary (default: {DEFAULT_MODEL})")
    parser.add_argument("--llm-timeout", type=float, default=DEFAULT_TIMEOUT_S,
                        help=f"seconds allowed for one local generation (default: {DEFAULT_TIMEOUT_S:.0f})")
    parser.add_argument("--no-llm", action="store_true", help="disable local Ollama commentary")
    parser.add_argument("--context-file", type=Path, default=None,
                        help="where to keep your goals and acknowledgements "
                             f"(default: {DEFAULT_ROOT}/<game>/player-context.json)")
    parser.add_argument("--no-context-file", action="store_true",
                        help="keep goals and acknowledgements for this run only")
    parser.add_argument("--no-tuner", action="store_true",
                        help="Never contact Civilization VI's tuner socket, even if "
                             "it is open.")
    args = parser.parse_args(argv)

    if args.logs_dir is not None and args.game is None:
        print(
            "--logs-dir needs --game: a log directory belongs to one game and the path "
            "does not say which.\n"
            f"Pass one of: {', '.join(profile_ids())}.",
            file=sys.stderr,
        )
        return 2

    game = args.game or default_game
    logs_dirs: dict[str, Path] = {}
    if game == AUTO:
        profile = None
        logs_dir = None
    else:
        try:
            profile = get_profile(game)
        except UnknownGame as exc:
            print(str(exc), file=sys.stderr)
            return 2
        logs_dir = args.logs_dir or profile.default_logs_dir
        if not logs_dir.is_dir():
            print(
                f"{profile.display_name} log directory not found: {logs_dir}\n"
                f"Start the game once so it creates the folder, or pass --logs-dir <path>.",
                file=sys.stderr,
            )
            return 2
        logs_dirs[profile.id] = logs_dir
    selector = GameSelector(pinned=None if game == AUTO else game, logs_dirs=logs_dirs)

    try:
        worker = None if args.no_llm else CommentaryWorker(
            OllamaClient(args.llm_model, timeout=args.llm_timeout)
        )
        # The copilot uses the same gate and the same client settings as the commentary:
        # one --no-llm turns both off, and there is never a run where one has a model and
        # the other does not. Its own client, because the two pools must not queue behind
        # each other -- a turn's commentary can take a large model minutes.
        copilot = None if args.no_llm else CopilotWorker(
            OllamaClient(args.llm_model, timeout=args.llm_timeout)
        )
    except ValueError as exc:
        parser.error(str(exc))
    # With --no-context-file the store is pointed at a throwaway path, so nothing is
    # written and nothing from a previous run is offered. --context-file names one file
    # for whichever game ends up active; with neither, create_app derives a per-game
    # path itself as the active game changes -- which matters most in --game auto,
    # where there is no game yet to derive a path from.
    fixed_notes = args.no_context_file or args.context_file is not None
    store_path = (Path(tempfile.mkdtemp(prefix="civ-context-")) / "player-context.json"
                  if args.no_context_file else args.context_file)
    app = create_app(logs_dir, args.poll_interval,
                     archive_root=args.archive_dir,
                     archiving=not args.no_archive,
                     commentary_worker=worker,
                     player_store=PersistentContextStore(path=store_path) if fixed_notes else None,
                     profile=profile, selector=selector,
                     storage_base=DEFAULT_ROOT, use_tuner=not args.no_tuner,
                     copilot_worker=copilot)
    # Task 5's notice, now against whichever game is pinned; with --game auto there is
    # no game yet and nothing is claimed about where a user's old data belongs.
    if profile is not None:
        _report_legacy_data(
            None if args.no_archive else (args.archive_dir or archive_root_for(profile.id)),
            store_path or store_path_for(profile.id))

    archive_root = None if args.no_archive else (
        args.archive_dir or (None if profile is None else archive_root_for(profile.id)))
    where = f"archiving to {archive_root}" if archive_root else "archiving off"
    llm = "LLM off" if worker is None else f"Ollama {args.llm_model}"
    notes = ("notes off" if args.no_context_file else
             f"notes in {store_path}" if store_path is not None else
             f"notes under {DEFAULT_ROOT}/<game>")
    which = "detecting the game each poll" if profile is None else \
        f"{profile.display_name}, reading {logs_dir}"
    print(f"Civ Advisor -> http://{args.host}:{args.port}  ({which}; {where}; {llm}; {notes})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _report_legacy_data(archive_root: Path | None, store_path: Path | None) -> None:
    """Say where a pre-2b install's data is, once, and how to adopt it.

    Storage is now per game, so the old single-rooted directory is not read by default.
    Printing this is the alternative to two unacceptable options: moving a user's files
    without asking, or leaving them where nothing mentions them again.
    """
    for legacy, current, what, flag in (
        (LEGACY_ARCHIVE_ROOT, archive_root, "archived logs", "--archive-dir"),
        (LEGACY_STORE_PATH, store_path, "goals and acknowledgements", "--context-file"),
    ):
        if current is None or not legacy.exists() or current.exists():
            continue
        print(f"note: your earlier {what} are still at {legacy}. Storage is now per game.\n"
              f"      To adopt them:  mv {legacy} {current}\n"
              f"      Or keep using them where they are with {flag} {legacy}",
              file=sys.stderr)


def _archive_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="civ-advisor archive")
    parser.add_argument("action", choices=["list"])
    parser.add_argument("--archive-dir", type=Path, default=None,
                        help="the BASE directory holding every game's own archive "
                             "subfolder -- NOT the same meaning as the top-level "
                             "civ-advisor command's own --archive-dir, which names a "
                             f"single flat destination (default: {DEFAULT_ROOT})")
    args = parser.parse_args(argv)
    roots: list[tuple[Path, str]] = []
    base = args.archive_dir or DEFAULT_ROOT
    for game in sorted(profile_ids()):
        root = archive_root_for(game, base=base)
        if root.is_dir():
            roots.append((root, game))
    if LEGACY_ARCHIVE_ROOT.is_dir():
        roots.append((LEGACY_ARCHIVE_ROOT, "civ7 (pre-2b)"))
    if not roots:
        print(f"No archive at {base}")
        return 0
    for root, label in roots:
        for key in sorted(p for p in root.iterdir() if p.is_dir()):
            for session in sorted(p for p in key.iterdir() if p.is_dir()):
                manifest = session / MANIFEST
                files, updated = [], "?"
                if manifest.is_file():
                    data = json.loads(manifest.read_text())
                    files, updated = data.get("files", []), data.get("updated", "?")
                n = len(files)
                print(f"{label}  {key.name}  {session.name}  "
                      f"{n} file{'s' if n != 1 else ''}  updated {updated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
