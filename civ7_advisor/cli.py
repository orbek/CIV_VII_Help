"""`civ7-advisor` command: start the dashboard server."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from civ7_advisor.api.app import create_app

DEFAULT_LOGS_DIR = Path.home() / "Library/Application Support/Civilization VII/Logs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="civ7-advisor",
        description="Second-screen turn advisor for Civilization VII. Reads the game's own log "
                    "files; never writes to them.",
    )
    parser.add_argument("--logs-dir", type=Path, default=DEFAULT_LOGS_DIR,
                        help=f"Civ VII Logs directory (default: {DEFAULT_LOGS_DIR})")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--poll-interval", type=float, default=1.0,
                        help="seconds between checks of the log files (default 1.0)")
    args = parser.parse_args(argv)

    if not args.logs_dir.is_dir():
        print(
            f"Civ VII log directory not found: {args.logs_dir}\n"
            f"Start the game once so it creates the folder, or pass --logs-dir <path>.",
            file=sys.stderr,
        )
        return 2

    app = create_app(args.logs_dir, args.poll_interval)
    print(f"Civ VII Advisor -> http://{args.host}:{args.port}  (reading {args.logs_dir})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
