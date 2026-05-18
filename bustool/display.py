"""
bustool/display.py
------------------
Responsible for all terminal output formatting.

Keeping display logic separate from business logic means you can swap out
the presentation layer (e.g. add colour, a GUI, or a web front-end) without
touching the API or CLI modules.

All public functions accept plain Python dicts/lists as returned by
``bustool.api.GTFSData`` and write directly to stdout.
"""

# ANSI colour helpers (work on Windows 10 v1511+ and all Unix terminals)
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_CYAN   = "\033[96m"
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_RED    = "\033[91m"
_DIM    = "\033[2m"


def print_banner() -> None:
    """Print the application welcome banner."""
    print(f"\n{_BOLD}{_CYAN}╔══════════════════════════════════════╗")
    print(f"║   🚌  Brisbane TransLink Bus Lookup  ║")
    print(f"╚══════════════════════════════════════╝{_RESET}\n")


def print_help() -> None:
    """Print the list of available commands."""
    print(f"\n{_BOLD}Available commands:{_RESET}")
    print(f"  {_CYAN}search <name>{_RESET}    – Search for stops by name or suburb")
    print(f"  {_CYAN}route <number>{_RESET}   – Look up routes by number or name")
    print(f"  {_CYAN}next <stop_code>{_RESET} – Show next departures for a stop code")
    print(f"  {_CYAN}help{_RESET}             – Show this help message")
    print(f"  {_CYAN}quit{_RESET}             – Exit the application\n")


def print_loading(message: str) -> None:
    """Print a status/loading message."""
    print(f"{_DIM}{message}{_RESET}", flush=True)


def print_stops(stops: list[dict]) -> None:
    """Print a formatted table of stop search results.

    Parameters
    ----------
    stops:
        List of stop dicts as returned by ``GTFSData.search_stops()``.
        Expected keys: ``stop_code``, ``stop_name``, ``stop_lat``, ``stop_lon``.
    """
    if not stops:
        print(f"{_YELLOW}No stops found matching that search.{_RESET}")
        return

    print(f"\n{_BOLD}{'Stop Code':<12} {'Stop Name'}{_RESET}")
    print("─" * 65)
    for stop in stops:
        code = stop.get("stop_code", "—")
        name = stop.get("stop_name", "—")
        print(f"{_CYAN}{code:<12}{_RESET} {name}")
    print()


def print_routes(routes: list[dict]) -> None:
    """Print a formatted table of route search results.

    Parameters
    ----------
    routes:
        List of route dicts as returned by ``GTFSData.search_routes()``.
        Expected keys: ``route_short_name``, ``route_long_name``.
    """
    if not routes:
        print(f"{_YELLOW}No routes found matching that search.{_RESET}")
        return

    print(f"\n{_BOLD}{'Route':<10} {'Description'}{_RESET}")
    print("─" * 65)
    for route in routes:
        short = route.get("route_short_name", "—")
        long_ = route.get("route_long_name", "—")
        print(f"{_CYAN}{short:<10}{_RESET} {long_}")
    print()


def print_departures(stop_code: str, stop_name: str, departures: list[dict]) -> None:
    """Print a formatted table of upcoming departures.

    Parameters
    ----------
    stop_code:
        The stop code being queried (shown in the heading).
    stop_name:
        The human-readable stop name (shown in the heading).
    departures:
        List of departure dicts as returned by ``GTFSData.get_departures()``.
        Expected keys: ``route``, ``headsign``, ``departure``.
    """
    print(f"\n{_BOLD}Next departures from {_CYAN}{stop_code}{_RESET}{_BOLD} – {stop_name}:{_RESET}")

    if not departures:
        print(f"{_YELLOW}  No upcoming departures found for today.{_RESET}\n")
        return

    print(f"\n{_BOLD}{'Route':<8} {'Departs':<10} {'Destination'}{_RESET}")
    print("─" * 65)

    for dep in departures:
        route     = dep.get("route", "—")
        departure = dep.get("departure", "—")
        headsign  = dep.get("headsign", "—")
        print(f"{_CYAN}{route:<8}{_RESET} {_GREEN}{departure:<10}{_RESET} {headsign}")

    print()


def print_error(message: str) -> None:
    """Print a formatted error message."""
    print(f"{_RED}Error: {message}{_RESET}")
