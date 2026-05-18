"""
bustool/api.py
--------------
Downloads and parses the official TransLink South-East Queensland GTFS
static feed and provides three query functions:

  • search_stops(query)          – find stops by name keyword
  • search_routes(query)         – find routes by short or long name
  • get_departures(stop_code)    – next scheduled departures from a stop

GTFS feed URL (no API key required):
  https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip

The ZIP is cached on disk in a ``data/`` sub-folder next to this file.
Call ``GTFSData.load(refresh=True)`` to force a fresh download.

GTFS files used
---------------
stops.txt       stop_id, stop_code, stop_name, stop_lat, stop_lon
routes.txt      route_id, route_short_name, route_long_name
trips.txt       route_id, service_id, trip_id, trip_headsign, direction_id
stop_times.txt  trip_id, arrival_time, departure_time, stop_id, stop_sequence
calendar.txt    service_id, monday…sunday, start_date, end_date
calendar_dates.txt  service_id, date, exception_type
"""

from __future__ import annotations

import csv
import io
import os
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GTFS_URL = "https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip"
_DATA_DIR = Path(__file__).parent.parent / "data"
_ZIP_PATH = _DATA_DIR / "SEQ_GTFS.zip"

# How many hours before we consider the cached ZIP stale
_CACHE_MAX_AGE_HOURS = 24

# Days of the week as used in calendar.txt
_DOW = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_csv(z: zipfile.ZipFile, name: str) -> list[dict]:
    """Read a CSV file from the ZIP and return a list of row dicts."""
    with z.open(name) as f:
        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
        return list(reader)


def _parse_time(t: str) -> int:
    """Convert a GTFS HH:MM:SS time string to total seconds.

    GTFS allows hours >= 24 for trips that run past midnight.
    """
    h, m, s = t.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def _fmt_seconds(total: int) -> str:
    """Format total seconds back to HH:MM (clamped to 23:59 for display)."""
    h = (total // 3600) % 24
    m = (total % 3600) // 60
    return f"{h:02d}:{m:02d}"


# ---------------------------------------------------------------------------
# Main data class
# ---------------------------------------------------------------------------

class GTFSData:
    """In-memory representation of the TransLink GTFS static feed."""

    def __init__(self) -> None:
        # stop_code -> {stop_id, stop_code, stop_name, stop_lat, stop_lon}
        self.stops_by_code: dict[str, dict] = {}
        # stop_id -> same dict
        self.stops_by_id: dict[str, dict] = {}

        # route_id -> {route_id, route_short_name, route_long_name}
        self.routes: dict[str, dict] = {}

        # trip_id -> {route_id, service_id, trip_id, trip_headsign}
        self.trips: dict[str, dict] = {}
        # route_id -> list of trip dicts (same objects as self.trips values)
        self.trips_by_route: dict[str, list[dict]] = defaultdict(list)

        # stop_id -> list of {trip_id, arrival_time (str), departure_time (str), stop_sequence}
        self.stop_times_by_stop: dict[str, list[dict]] = defaultdict(list)
        # trip_id -> list of {stop_id, arrival_time (str), departure_time (str), stop_sequence}
        self.stop_times_by_trip: dict[str, list[dict]] = defaultdict(list)

        # stop_id -> set of route_ids that serve it (built after loading)
        self.routes_by_stop: dict[str, set[str]] = defaultdict(set)

        # service_id -> {monday…sunday, start_date, end_date}
        self.calendar: dict[str, dict] = {}

        # service_id -> set of date strings "YYYYMMDD" that are ADDED (exception_type=1)
        self.calendar_added: dict[str, set[str]] = defaultdict(set)
        # service_id -> set of date strings that are REMOVED (exception_type=2)
        self.calendar_removed: dict[str, set[str]] = defaultdict(set)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, refresh: bool = False) -> "GTFSData":
        """Download (if needed) and parse the GTFS ZIP.

        Parameters
        ----------
        refresh:
            When True, always download a fresh copy even if a cached file
            exists.  When False (default), the cached file is reused if it
            is less than 24 hours old.

        Returns
        -------
        GTFSData
            Fully populated instance ready for querying.
        """
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        need_download = refresh or not _ZIP_PATH.exists()
        if not need_download:
            age_hours = (
                datetime.now().timestamp() - _ZIP_PATH.stat().st_mtime
            ) / 3600
            if age_hours > _CACHE_MAX_AGE_HOURS:
                need_download = True

        if need_download:
            print("Downloading TransLink GTFS data (≈38 MB) …", flush=True)
            urllib.request.urlretrieve(GTFS_URL, _ZIP_PATH)
            print("Download complete.", flush=True)

        obj = cls()
        obj._parse(_ZIP_PATH)
        return obj

    def _parse(self, zip_path: Path) -> None:
        """Parse all required GTFS files from the ZIP."""
        with zipfile.ZipFile(zip_path) as z:
            self._load_stops(z)
            self._load_routes(z)
            self._load_trips(z)
            self._load_stop_times(z)
            self._load_calendar(z)
            self._load_calendar_dates(z)
        self._build_routes_by_stop()

    def _build_routes_by_stop(self) -> None:
        """Build stop_id -> set of route_ids index (run once after loading)."""
        for trip_id, trip in self.trips.items():
            route_id = trip["route_id"]
            for st in self.stop_times_by_trip.get(trip_id, []):
                self.routes_by_stop[st["stop_id"]].add(route_id)

    def _load_stops(self, z: zipfile.ZipFile) -> None:
        for row in _read_csv(z, "stops.txt"):
            entry = {
                "stop_id":   row["stop_id"],
                "stop_code": row["stop_code"],
                "stop_name": row["stop_name"],
                "stop_lat":  row.get("stop_lat", "").strip(),
                "stop_lon":  row.get("stop_lon", "").strip(),
            }
            self.stops_by_id[row["stop_id"]] = entry
            self.stops_by_code[row["stop_code"]] = entry

    def _load_routes(self, z: zipfile.ZipFile) -> None:
        for row in _read_csv(z, "routes.txt"):
            self.routes[row["route_id"]] = {
                "route_id":         row["route_id"],
                "route_short_name": row["route_short_name"],
                "route_long_name":  row["route_long_name"],
            }

    def _load_trips(self, z: zipfile.ZipFile) -> None:
        for row in _read_csv(z, "trips.txt"):
            entry = {
                "trip_id":       row["trip_id"],
                "route_id":      row["route_id"],
                "service_id":    row["service_id"],
                "trip_headsign": row.get("trip_headsign", ""),
            }
            self.trips[row["trip_id"]] = entry
            self.trips_by_route[row["route_id"]].append(entry)

    def _load_stop_times(self, z: zipfile.ZipFile) -> None:
        with z.open("stop_times.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                stop_id = row["stop_id"]
                trip_id = row["trip_id"]
                seq = int(row["stop_sequence"])
                arr = row["arrival_time"]
                dep = row["departure_time"]
                self.stop_times_by_stop[stop_id].append({
                    "trip_id":        trip_id,
                    "arrival_time":   arr,
                    "departure_time": dep,
                    "stop_sequence":  seq,
                })
                self.stop_times_by_trip[trip_id].append({
                    "stop_id":        stop_id,
                    "arrival_time":   arr,
                    "departure_time": dep,
                    "stop_sequence":  seq,
                })

    def _load_calendar(self, z: zipfile.ZipFile) -> None:
        for row in _read_csv(z, "calendar.txt"):
            self.calendar[row["service_id"]] = row

    def _load_calendar_dates(self, z: zipfile.ZipFile) -> None:
        for row in _read_csv(z, "calendar_dates.txt"):
            sid = row["service_id"]
            d   = row["date"]
            if row["exception_type"] == "1":
                self.calendar_added[sid].add(d)
            else:
                self.calendar_removed[sid].add(d)

    # ------------------------------------------------------------------
    # Service-day helpers
    # ------------------------------------------------------------------

    def _is_service_running(self, service_id: str, on_date: date) -> bool:
        """Return True if *service_id* operates on *on_date*."""
        date_str = on_date.strftime("%Y%m%d")

        # calendar_dates overrides take priority
        if date_str in self.calendar_added.get(service_id, set()):
            return True
        if date_str in self.calendar_removed.get(service_id, set()):
            return False

        cal = self.calendar.get(service_id)
        if cal is None:
            return False

        # Check date range
        if not (cal["start_date"] <= date_str <= cal["end_date"]):
            return False

        # Check day-of-week flag
        dow_name = _DOW[on_date.weekday()]
        return cal.get(dow_name, "0") == "1"

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def search_stops(self, query: str, limit: int = 10) -> list[dict]:
        """Return stops whose name contains *query* (case-insensitive).

        Parameters
        ----------
        query:
            Partial stop name or suburb, e.g. ``"Roma Street"`` or ``"Indooroopilly"``.
        limit:
            Maximum number of results to return (default 10).

        Returns
        -------
        list[dict]
            Each dict has keys: ``stop_code``, ``stop_name``, ``stop_lat``, ``stop_lon``.
        """
        q = query.lower()
        results = [
            s for s in self.stops_by_id.values()
            if q in s["stop_name"].lower()
        ]
        results.sort(key=lambda s: s["stop_name"])
        return results[:limit]

    def search_routes(self, query: str, limit: int = 10) -> list[dict]:
        """Return routes whose short or long name contains *query*.

        Parameters
        ----------
        query:
            Route number or partial name, e.g. ``"333"`` or ``"Eight Mile Plains"``.
        limit:
            Maximum number of results to return (default 10).

        Returns
        -------
        list[dict]
            Each dict has keys: ``route_id``, ``route_short_name``, ``route_long_name``.
        """
        q = query.lower()
        results = [
            r for r in self.routes.values()
            if q in r["route_short_name"].lower() or q in r["route_long_name"].lower()
        ]
        results.sort(key=lambda r: r["route_short_name"])
        return results[:limit]

    def get_departures(
        self,
        stop_code: str,
        count: int = 10,
        on_date: date | None = None,
        after_time: int | None = None,
    ) -> list[dict]:
        """Return the next scheduled departures from a stop.

        Parameters
        ----------
        stop_code:
            The 6-digit TransLink stop code printed on the bus stop sign
            (e.g. ``"000007"``).
        count:
            Maximum number of upcoming departures to return (default 10).
        on_date:
            The date to query.  Defaults to today (Brisbane local time).
        after_time:
            Seconds-since-midnight lower bound.  Defaults to now.

        Returns
        -------
        list[dict]
            Sorted by departure time.  Each dict has:
            ``route``, ``headsign``, ``departure``, ``stop_code``.

        Raises
        ------
        ValueError
            If *stop_code* is not found in the GTFS data.
        """
        stop = self.stops_by_code.get(stop_code)
        if stop is None:
            raise ValueError(f"Stop code '{stop_code}' not found in GTFS data.")

        stop_id = stop["stop_id"]

        if on_date is None:
            on_date = date.today()
        if after_time is None:
            now = datetime.now()
            after_time = now.hour * 3600 + now.minute * 60 + now.second

        # Also look at tomorrow for services that run past midnight
        dates_to_check = [on_date, on_date + timedelta(days=1)]

        departures: list[dict] = []

        for st in self.stop_times_by_stop.get(stop_id, []):
            dep_secs = _parse_time(st["departure_time"])

            for check_date in dates_to_check:
                # For tomorrow, only include services whose GTFS time >= 24h
                # (i.e. they are a continuation of a service that started yesterday)
                if check_date == on_date + timedelta(days=1) and dep_secs < 86400:
                    continue

                trip = self.trips.get(st["trip_id"])
                if trip is None:
                    continue

                if not self._is_service_running(trip["service_id"], check_date):
                    continue

                # Normalise time for comparison: subtract 24h for next-day trips
                effective_secs = dep_secs if check_date == on_date else dep_secs - 86400

                if effective_secs < after_time:
                    continue

                route = self.routes.get(trip["route_id"], {})
                departures.append({
                    "route":      route.get("route_short_name", "?"),
                    "headsign":   trip["trip_headsign"],
                    "departure":  _fmt_seconds(dep_secs),
                    "stop_code":  stop_code,
                    "_sort_key":  effective_secs,
                })

        departures.sort(key=lambda d: d["_sort_key"])
        # Remove internal sort key before returning
        for d in departures:
            del d["_sort_key"]

        return departures[:count]
