"""
main.py
-------
Entry point for the Brisbane TransLink Bus Lookup app.

Run the app from the project root with:

    python main.py

Add --refresh to force a fresh download of the GTFS data:

    python main.py --refresh

The GTFS ZIP is cached in the ``data/`` folder and reused automatically
for 24 hours before being re-downloaded.  No API key is required.
"""

import argparse
from bustool import cli


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="bustool",
        description="Brisbane TransLink bus stop lookup tool (uses GTFS static data).",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        default=False,
        help=(
            "Force a fresh download of the TransLink GTFS ZIP, "
            "ignoring any locally cached copy."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    cli.run(refresh=args.refresh)
