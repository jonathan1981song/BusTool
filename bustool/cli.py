"""
bustool/cli.py
--------------
Implements the interactive command-line REPL (Read-Eval-Print Loop).

The CLI loads the GTFS data once at startup, then reads commands from stdin,
delegates work to the API layer (GTFSData), and passes results to the display
layer.  It knows nothing about HTTP, file parsing, or formatting.

Supported commands
------------------
  search <name>    – find stops matching a name or suburb
  route <query>    – find routes by number or name
  next <stop_code> – show the next departures for a stop code
  help             – print usage information
  quit / exit      – exit the application
"""

from __future__ import annotations

from bustool.api import GTFSData
from bustool import display


def run(refresh: bool = False) -> None:
    """Start the interactive bus-lookup REPL.

    Parameters
    ----------
    refresh:
        When True, force a fresh download of the GTFS ZIP even if a
        cached copy exists.
    """
    display.print_banner()
    display.print_loading("Loading GTFS data (this may take a moment on first run) …")

    try:
        gtfs = GTFSData.load(refresh=refresh)
    except Exception as exc:
        display.print_error(f"Failed to load GTFS data: {exc}")
        return

    display.print_loading("Ready.\n")
    display.print_help()

    while True:
        try:
            raw = input("bustool> ").strip()
        except (EOFError, KeyboardInterrupt):
            # Ctrl-D or Ctrl-C exits cleanly
            print("\nGoodbye! 🚌")
            break

        if not raw:
            continue

        parts   = raw.split(maxsplit=1)
        command = parts[0].lower()
        arg     = parts[1].strip() if len(parts) > 1 else ""

        # ── quit ──────────────────────────────────────────────────────
        if command in ("quit", "exit", "q"):
            print("Goodbye! 🚌")
            break

        # ── help ──────────────────────────────────────────────────────
        elif command == "help":
            display.print_help()

        # ── search <name> ─────────────────────────────────────────────
        elif command == "search":
            if not arg:
                display.print_error("Usage: search <stop name or suburb>")
                continue
            stops = gtfs.search_stops(arg)
            display.print_stops(stops)

        # ── route <query> ─────────────────────────────────────────────
        elif command == "route":
            if not arg:
                display.print_error("Usage: route <route number or name>")
                continue
            routes = gtfs.search_routes(arg)
            display.print_routes(routes)

        # ── next <stop_code> ──────────────────────────────────────────
        elif command == "next":
            if not arg:
                display.print_error("Usage: next <stop_code>  (e.g. next 000007)")
                continue
            try:
                departures = gtfs.get_departures(arg)
                stop       = gtfs.stops_by_code.get(arg, {})
                stop_name  = stop.get("stop_name", arg)
                display.print_departures(arg, stop_name, departures)
            except ValueError as exc:
                display.print_error(str(exc))

        # ── unknown ───────────────────────────────────────────────────
        else:
            display.print_error(
                f"Unknown command '{command}'.  Type 'help' for a list of commands."
            )
