# 🚌 Brisbane TransLink Bus Lookup

A simple Python app for searching Brisbane bus stops, looking up routes, and
viewing scheduled timetables — powered entirely by the **official TransLink
GTFS static feed** (no API key required).

Available as both a **command-line interface (CLI)** and a **mobile-friendly
web application** designed for elderly users with large text and buttons.

---

## Quick Start

### Web Application (Recommended for most users)

```bash
# Install Flask (one-time)
python -m pip install flask

# Start the web server
python app.py
```

Then open your web browser and go to **http://localhost:5000**

### Command-Line Interface

```bash
python main.py
```

---

## Project Structure

```
BusTool/
├── bustool/
│   ├── __init__.py   # Package init – exposes GTFSData
│   ├── api.py        # Downloads & parses the GTFS ZIP; all query logic
│   ├── cli.py        # Interactive REPL (command-line interface)
│   └── display.py    # All terminal formatting / pretty-printing
├── templates/        # HTML templates for the web app
│   ├── index.html       # Homepage with route search
│   ├── route_detail.html # Route info and stops list
│   ├── timetable.html    # Timetable with day selector
│   └── error.html        # Error page
├── static/           # Static assets for the web app
│   └── css/
│       └── style.css # Elderly-friendly styling
├── data/             # Auto-created; stores the cached SEQ_GTFS.zip
├── app.py            # Flask web application entry point
├── main.py           # CLI entry point – parses args and starts the REPL
├── requirements.txt  # Python dependencies (Flask for web app)
└── README.md         # This file
```

### File explanations

| File | Purpose |
|------|---------|
| `bustool/__init__.py` | Makes `bustool` a Python package; re-exports `GTFSData` so callers can write `from bustool import GTFSData`. |
| `bustool/api.py` | Contains the `GTFSData` class. On first run it downloads the TransLink GTFS ZIP (~38 MB) and caches it in `data/`. It parses `stops.txt`, `routes.txt`, `trips.txt`, `stop_times.txt`, `calendar.txt`, and `calendar_dates.txt` into in-memory dicts for fast querying. Provides `search_stops()`, `search_routes()`, and `get_departures()`. |
| `bustool/display.py` | Pure presentation layer. Formats stops, routes, and departures into coloured terminal tables using ANSI escape codes. Has no knowledge of HTTP, file I/O, or business logic. |
| `bustool/cli.py` | The REPL loop. Reads user input, calls the appropriate `GTFSData` method, and passes results to the display layer. Handles `Ctrl-C` / `Ctrl-D` gracefully. |
| `app.py` | Flask web application. Provides routes for homepage, route search, route details, and timetables. Loads GTFS data once at startup. |
| `main.py` | CLI entry point. Parses the optional `--refresh` flag and calls `cli.run()`. |
| `requirements.txt` | Python dependencies. Flask required for web app; CLI uses stdlib only. |

---

## Data Source

The app uses the **TransLink South-East Queensland GTFS static feed**:

```
https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip
```

- **No API key required.**
- The ZIP (~38 MB) is downloaded automatically on first run and cached in
  `data/SEQ_GTFS.zip`.
- The cache is reused for 24 hours, then refreshed automatically.
- Use `python main.py --refresh` to force an immediate re-download.

---

## Prerequisites

- **Python 3.10 or newer** (uses `X | Y` union type hints)
- Internet access for the initial GTFS download

---

## Installation

```bash
# 1. Clone / download the project
cd c:\Projects\BusTool

# 2. (Optional but recommended) create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# 3. No pip install needed – stdlib only!
```

---

## Usage

```bash
python main.py
```

On first run the GTFS data is downloaded (~38 MB). Subsequent runs load from
the local cache instantly.

```bash
# Force a fresh download of the GTFS data
python main.py --refresh
```

Once running, you will see an interactive prompt:

```
╔══════════════════════════════════════╗
║   🚌  Brisbane TransLink Bus Lookup  ║
╚══════════════════════════════════════╝

Available commands:
  search <name>    – Search for stops by name or suburb
  route <number>   – Look up routes by number or name
  next <stop_code> – Show next departures for a stop code
  help             – Show this help message
  quit             – Exit the application

bustool>
```

### Example session

```
bustool> search Roma Street
Stop Code    Stop Name
─────────────────────────────────────────────────────────────────
000007       Roma Street Platform 1 near Roma Street Station
000008       Roma Street Platform 2 near Roma Street Station
...

bustool> route 333
Route      Description
─────────────────────────────────────────────────────────────────
333        Eight Mile Plains - City

bustool> next 000007
Next departures from 000007 – Roma Street Platform 1 near Roma Street Station:

Route    Departs    Destination
─────────────────────────────────────────────────────────────────
333      13:15      Eight Mile Plains
61       13:22      Inala
...

bustool> quit
Goodbye! 🚌
```

---

## How departures are calculated

1. The stop code is looked up in `stops.txt` to get the internal `stop_id`.
2. All `stop_times.txt` entries for that `stop_id` are retrieved.
3. For each entry the associated `trip_id` → `service_id` is checked against
   `calendar.txt` and `calendar_dates.txt` to confirm the service runs today.
4. Only departures after the current time are kept, sorted, and the first 10
   are displayed.

---

## Notes

- ANSI colours work out-of-the-box on Windows 10 v1511+ and all modern
  macOS / Linux terminals.
- GTFS times can exceed 23:59 (e.g. `25:30:00` means 1:30 AM the next day).
  The app handles this correctly.
