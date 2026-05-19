"""
bustool/api.py
--------------
SQLite-backed GTFS data store for TransLink South-East Queensland.

On first run: downloads the GTFS zip (~38 MB) and builds a SQLite database.
Subsequent runs reuse the database, keeping RAM well under 512 MB.
"""

from __future__ import annotations

import csv
import io
import math
import sqlite3
import threading
import urllib.request
import zipfile
from datetime import date, datetime
from pathlib import Path

GTFS_URL = "https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip"
_DATA_DIR = Path(__file__).parent.parent / "data"
_ZIP_PATH = _DATA_DIR / "SEQ_GTFS.zip"
_DB_PATH  = _DATA_DIR / "gtfs.db"
_CACHE_MAX_AGE_HOURS = 24
_DOW = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _read_csv(z: zipfile.ZipFile, name: str) -> list[dict]:
    with z.open(name) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class GTFSData:
    """SQLite-backed GTFS data. Thread-safe via thread-local connections."""

    def __init__(self) -> None:
        self._local = threading.local()

    # ------------------------------------------------------------------ #
    # Connection
    # ------------------------------------------------------------------ #

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(str(_DB_PATH))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA cache_size=-16000")
            conn.execute("PRAGMA temp_store=MEMORY")
            self._local.conn = conn
        return self._local.conn

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls, refresh: bool = False) -> "GTFSData":
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        need_download = refresh or not _ZIP_PATH.exists()
        if not need_download:
            age = (datetime.now().timestamp() - _ZIP_PATH.stat().st_mtime) / 3600
            if age > _CACHE_MAX_AGE_HOURS:
                need_download = True

        if need_download:
            print("Downloading TransLink GTFS data (~38 MB)…", flush=True)
            urllib.request.urlretrieve(GTFS_URL, _ZIP_PATH)
            print("Download complete.", flush=True)

        obj = cls()
        if need_download or not _DB_PATH.exists():
            print("Building SQLite database…", flush=True)
            obj._build_db()
            print("Database ready.", flush=True)
        return obj

    def _build_db(self) -> None:
        if _DB_PATH.exists():
            _DB_PATH.unlink()

        conn = sqlite3.connect(str(_DB_PATH))
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")

        conn.executescript("""
            CREATE TABLE stops (
                stop_id   TEXT,
                stop_code TEXT,
                stop_name TEXT,
                stop_lat  REAL,
                stop_lon  REAL
            );
            CREATE TABLE routes (
                route_id         TEXT,
                route_short_name TEXT,
                route_long_name  TEXT
            );
            CREATE TABLE trips (
                trip_id       TEXT,
                route_id      TEXT,
                service_id    TEXT,
                trip_headsign TEXT
            );
            CREATE TABLE stop_times (
                trip_id       TEXT,
                stop_id       TEXT,
                dep_secs      INTEGER,
                stop_sequence INTEGER
            );
            CREATE TABLE calendar (
                service_id TEXT,
                monday     INTEGER, tuesday  INTEGER, wednesday INTEGER,
                thursday   INTEGER, friday   INTEGER, saturday  INTEGER,
                sunday     INTEGER,
                start_date TEXT,    end_date  TEXT
            );
            CREATE TABLE calendar_dates (
                service_id     TEXT,
                date           TEXT,
                exception_type INTEGER
            );
        """)

        with zipfile.ZipFile(_ZIP_PATH) as z:
            rows = _read_csv(z, "stops.txt")
            conn.executemany("INSERT INTO stops VALUES (?,?,?,?,?)", [
                (r["stop_id"], r.get("stop_code", ""), r["stop_name"],
                 float(r.get("stop_lat") or 0), float(r.get("stop_lon") or 0))
                for r in rows
            ])
            print(f"  stops: {len(rows)}", flush=True)

            rows = _read_csv(z, "routes.txt")
            conn.executemany("INSERT INTO routes VALUES (?,?,?)", [
                (r["route_id"], r["route_short_name"], r["route_long_name"])
                for r in rows
            ])
            print(f"  routes: {len(rows)}", flush=True)

            rows = _read_csv(z, "trips.txt")
            conn.executemany("INSERT INTO trips VALUES (?,?,?,?)", [
                (r["trip_id"], r["route_id"], r["service_id"],
                 r.get("trip_headsign", ""))
                for r in rows
            ])
            print(f"  trips: {len(rows)}", flush=True)

            count = 0
            with z.open("stop_times.txt") as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                batch: list = []
                for row in reader:
                    dep = row["departure_time"]
                    try:
                        h, m, s = dep.split(":")
                        secs = int(h) * 3600 + int(m) * 60 + int(s)
                    except Exception:
                        secs = 0
                    batch.append((
                        row["trip_id"], row["stop_id"],
                        secs, int(row["stop_sequence"]),
                    ))
                    if len(batch) >= 100_000:
                        conn.executemany("INSERT INTO stop_times VALUES (?,?,?,?)", batch)
                        count += len(batch)
                        batch.clear()
                if batch:
                    conn.executemany("INSERT INTO stop_times VALUES (?,?,?,?)", batch)
                    count += len(batch)
            print(f"  stop_times: {count}", flush=True)

            rows = _read_csv(z, "calendar.txt")
            conn.executemany("INSERT INTO calendar VALUES (?,?,?,?,?,?,?,?,?,?)", [
                (r["service_id"],
                 int(r.get("monday", 0)), int(r.get("tuesday", 0)),
                 int(r.get("wednesday", 0)), int(r.get("thursday", 0)),
                 int(r.get("friday", 0)), int(r.get("saturday", 0)),
                 int(r.get("sunday", 0)),
                 r["start_date"], r["end_date"])
                for r in rows
            ])

            rows = _read_csv(z, "calendar_dates.txt")
            conn.executemany("INSERT INTO calendar_dates VALUES (?,?,?)", [
                (r["service_id"], r["date"], int(r["exception_type"]))
                for r in rows
            ])

        print("  Building indexes…", flush=True)
        conn.executescript("""
            CREATE INDEX idx_stops_code ON stops(stop_code);
            CREATE INDEX idx_trips_route ON trips(route_id);
            CREATE INDEX idx_st_stop ON stop_times(stop_id, dep_secs);
            CREATE INDEX idx_st_trip ON stop_times(trip_id, stop_sequence);
            CREATE INDEX idx_cd ON calendar_dates(service_id, date);
        """)
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------ #
    # Service-day helpers
    # ------------------------------------------------------------------ #

    def get_active_service_ids(self, on_date: date) -> set[str]:
        date_str = on_date.strftime("%Y%m%d")
        dow = _DOW[on_date.weekday()]
        c = self._conn()
        rows = c.execute(
            f"SELECT service_id FROM calendar "
            f"WHERE {dow}=1 AND start_date<=? AND end_date>=?",
            (date_str, date_str)
        ).fetchall()
        active = {r[0] for r in rows}
        for sid, exc in c.execute(
            "SELECT service_id, exception_type FROM calendar_dates WHERE date=?",
            (date_str,)
        ).fetchall():
            if exc == 1:
                active.add(sid)
            else:
                active.discard(sid)
        return active

    def get_service_ids_for_day_type(self, day_type: str) -> set[str]:
        if day_type == "weekday":
            col = "monday=1 OR tuesday=1 OR wednesday=1 OR thursday=1 OR friday=1"
        elif day_type == "saturday":
            col = "saturday=1"
        elif day_type == "sunday":
            col = "sunday=1"
        else:
            return set()
        rows = self._conn().execute(
            f"SELECT service_id FROM calendar WHERE {col}"
        ).fetchall()
        return {r[0] for r in rows}

    # ------------------------------------------------------------------ #
    # Single-object lookups
    # ------------------------------------------------------------------ #

    def get_route(self, route_id: str) -> dict | None:
        r = self._conn().execute(
            "SELECT * FROM routes WHERE route_id=?", (route_id,)
        ).fetchone()
        return dict(r) if r else None

    def get_stop_by_id(self, stop_id: str) -> dict | None:
        r = self._conn().execute(
            "SELECT * FROM stops WHERE stop_id=?", (stop_id,)
        ).fetchone()
        return dict(r) if r else None

    def get_stop_by_code(self, stop_code: str) -> dict | None:
        r = self._conn().execute(
            "SELECT * FROM stops WHERE stop_code=?", (stop_code,)
        ).fetchone()
        return dict(r) if r else None

    # ------------------------------------------------------------------ #
    # Route / stop lists
    # ------------------------------------------------------------------ #

    def get_direction_stops(self, route_id: str, direction: str) -> list[dict]:
        """Unique stops for a route+direction in stop_sequence order."""
        c = self._conn()
        if direction:
            rows = c.execute(
                "SELECT st.stop_id, s.stop_name, MIN(st.stop_sequence) as seq "
                "FROM trips t "
                "JOIN stop_times st ON t.trip_id=st.trip_id "
                "JOIN stops s ON st.stop_id=s.stop_id "
                "WHERE t.route_id=? AND LOWER(t.trip_headsign) LIKE ? "
                "GROUP BY st.stop_id ORDER BY MIN(st.stop_sequence)",
                (route_id, f"%{direction.lower()}%")
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT st.stop_id, s.stop_name, MIN(st.stop_sequence) as seq "
                "FROM trips t "
                "JOIN stop_times st ON t.trip_id=st.trip_id "
                "JOIN stops s ON st.stop_id=s.stop_id "
                "WHERE t.route_id=? "
                "GROUP BY st.stop_id ORDER BY MIN(st.stop_sequence)",
                (route_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_route_all_stops(self, route_id: str) -> list[dict]:
        rows = self._conn().execute(
            "SELECT st.stop_id, s.stop_code, s.stop_name, s.stop_lat, s.stop_lon, "
            "       MIN(st.stop_sequence) as seq "
            "FROM trips t "
            "JOIN stop_times st ON t.trip_id=st.trip_id "
            "JOIN stops s ON st.stop_id=s.stop_id "
            "WHERE t.route_id=? "
            "GROUP BY st.stop_id ORDER BY MIN(st.stop_sequence)",
            (route_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_route_stops_with_headsign(self, route_id: str) -> list[dict]:
        rows = self._conn().execute(
            "SELECT st.stop_id, s.stop_name, s.stop_lat, s.stop_lon, t.trip_headsign "
            "FROM trips t "
            "JOIN stop_times st ON t.trip_id=st.trip_id "
            "JOIN stops s ON st.stop_id=s.stop_id "
            "WHERE t.route_id=? "
            "GROUP BY st.stop_id",
            (route_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Departure queries
    # ------------------------------------------------------------------ #

    def get_next_departures(
        self,
        route_id: str,
        service_ids: set[str],
        after_secs: int,
        direction: str = "",
        limit: int = 30,
    ) -> list[dict]:
        if not service_ids:
            return []
        ph = ",".join("?" * len(service_ids))
        c = self._conn()
        if direction:
            rows = c.execute(
                f"SELECT DISTINCT st.dep_secs, t.trip_headsign, "
                f"       st.stop_id, s.stop_name, s.stop_code "
                f"FROM trips t "
                f"JOIN stop_times st ON t.trip_id=st.trip_id "
                f"JOIN stops s ON st.stop_id=s.stop_id "
                f"WHERE t.route_id=? AND t.service_id IN ({ph}) AND st.dep_secs>? "
                f"  AND LOWER(t.trip_headsign) LIKE ? "
                f"ORDER BY st.dep_secs LIMIT ?",
                (route_id, *service_ids, after_secs, f"%{direction.lower()}%", limit)
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT DISTINCT st.dep_secs, t.trip_headsign, "
                f"       st.stop_id, s.stop_name, s.stop_code "
                f"FROM trips t "
                f"JOIN stop_times st ON t.trip_id=st.trip_id "
                f"JOIN stops s ON st.stop_id=s.stop_id "
                f"WHERE t.route_id=? AND t.service_id IN ({ph}) AND st.dep_secs>? "
                f"ORDER BY st.dep_secs LIMIT ?",
                (route_id, *service_ids, after_secs, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_departures_for_stops(
        self,
        stop_ids: list[str],
        service_ids: set[str],
        after_secs: int,
    ) -> list[dict]:
        if not stop_ids or not service_ids:
            return []
        ph_s = ",".join("?" * len(stop_ids))
        ph_v = ",".join("?" * len(service_ids))
        rows = self._conn().execute(
            f"SELECT st.stop_id, st.dep_secs, t.route_id, t.trip_headsign, "
            f"       r.route_short_name, r.route_long_name "
            f"FROM stop_times st "
            f"JOIN trips t ON st.trip_id=t.trip_id "
            f"JOIN routes r ON t.route_id=r.route_id "
            f"WHERE st.stop_id IN ({ph_s}) AND st.dep_secs>? AND t.service_id IN ({ph_v}) "
            f"ORDER BY st.dep_secs",
            (*stop_ids, after_secs, *service_ids)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_routes_at_stops(self, stop_ids: list[str]) -> list[dict]:
        if not stop_ids:
            return []
        ph = ",".join("?" * len(stop_ids))
        rows = self._conn().execute(
            f"SELECT DISTINCT t.route_id, r.route_short_name, r.route_long_name, st.stop_id "
            f"FROM stop_times st "
            f"JOIN trips t ON st.trip_id=t.trip_id "
            f"JOIN routes r ON t.route_id=r.route_id "
            f"WHERE st.stop_id IN ({ph})",
            stop_ids
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Timetable queries
    # ------------------------------------------------------------------ #

    def get_timetable_at_stop(
        self, route_id: str, stop_id: str, service_ids: set[str]
    ) -> list[dict]:
        if not service_ids:
            return []
        from collections import defaultdict
        ph = ",".join("?" * len(service_ids))
        rows = self._conn().execute(
            f"SELECT t.trip_headsign, st.dep_secs "
            f"FROM trips t JOIN stop_times st ON t.trip_id=st.trip_id "
            f"WHERE t.route_id=? AND st.stop_id=? AND t.service_id IN ({ph}) "
            f"ORDER BY st.dep_secs",
            (route_id, stop_id, *service_ids)
        ).fetchall()
        d: dict = defaultdict(list)
        for r in rows:
            s = r[1]
            d[r[0]].append(f"{s//3600:02d}:{(s%3600)//60:02d}")
        return [{"headsign": h, "times": times} for h, times in d.items()]

    def get_timetable_origin(
        self, route_id: str, service_ids: set[str]
    ) -> list[dict]:
        if not service_ids:
            return []
        from collections import defaultdict
        ph = ",".join("?" * len(service_ids))
        rows = self._conn().execute(
            f"SELECT t.trip_headsign, st.stop_id, s.stop_name, st.dep_secs "
            f"FROM trips t "
            f"JOIN stop_times st ON t.trip_id=st.trip_id "
            f"JOIN stops s ON st.stop_id=s.stop_id "
            f"WHERE t.route_id=? AND t.service_id IN ({ph}) "
            f"  AND st.stop_sequence=("
            f"    SELECT MIN(s2.stop_sequence) FROM stop_times s2 WHERE s2.trip_id=t.trip_id"
            f"  ) "
            f"ORDER BY st.dep_secs",
            (route_id, *service_ids)
        ).fetchall()
        data: dict = defaultdict(lambda: defaultdict(list))
        stop_names: dict = {}
        for r in rows:
            s = r["dep_secs"]
            data[r["trip_headsign"]][r["stop_id"]].append(f"{s//3600:02d}:{(s%3600)//60:02d}")
            stop_names[r["stop_id"]] = r["stop_name"]
        result = []
        for headsign, stops in data.items():
            for sid, times in stops.items():
                result.append({
                    "headsign": headsign,
                    "stop_name": stop_names[sid],
                    "times": times,
                })
        return result

    # ------------------------------------------------------------------ #
    # Nearby stops
    # ------------------------------------------------------------------ #

    def get_stops_near(
        self, lat: float, lon: float, radius_m: float
    ) -> list[tuple[str, float]]:
        lat_d = radius_m / 111_000
        lon_d = radius_m / (111_000 * math.cos(math.radians(lat)))
        rows = self._conn().execute(
            "SELECT stop_id, stop_lat, stop_lon FROM stops "
            "WHERE stop_lat BETWEEN ? AND ? AND stop_lon BETWEEN ? AND ?",
            (lat - lat_d, lat + lat_d, lon - lon_d, lon + lon_d)
        ).fetchall()
        result = []
        for r in rows:
            d = _haversine_m(lat, lon, r["stop_lat"], r["stop_lon"])
            if d <= radius_m:
                result.append((r["stop_id"], d))
        result.sort(key=lambda x: x[1])
        return result

    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #

    def search_stops(self, query: str, limit: int = 10) -> list[dict]:
        rows = self._conn().execute(
            "SELECT stop_code, stop_name, stop_lat, stop_lon FROM stops "
            "WHERE LOWER(stop_name) LIKE ? ORDER BY stop_name LIMIT ?",
            (f"%{query.lower()}%", limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def search_routes(self, query: str, limit: int = 10) -> list[dict]:
        q = f"%{query.lower()}%"
        rows = self._conn().execute(
            "SELECT route_id, route_short_name, route_long_name FROM routes "
            "WHERE LOWER(route_short_name) LIKE ? OR LOWER(route_long_name) LIKE ? "
            "ORDER BY route_short_name LIMIT ?",
            (q, q, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_departures(
        self,
        stop_code: str,
        count: int = 10,
        on_date: date | None = None,
        after_time: int | None = None,
    ) -> list[dict]:
        stop = self.get_stop_by_code(stop_code)
        if stop is None:
            raise ValueError(f"Stop code '{stop_code}' not found.")
        if on_date is None:
            on_date = date.today()
        if after_time is None:
            now = datetime.now()
            after_time = now.hour * 3600 + now.minute * 60 + now.second
        service_ids = self.get_active_service_ids(on_date)
        if not service_ids:
            return []
        ph = ",".join("?" * len(service_ids))
        rows = self._conn().execute(
            f"SELECT st.dep_secs, t.trip_headsign, r.route_short_name "
            f"FROM stop_times st "
            f"JOIN trips t ON st.trip_id=t.trip_id "
            f"JOIN routes r ON t.route_id=r.route_id "
            f"WHERE st.stop_id=? AND st.dep_secs>? AND t.service_id IN ({ph}) "
            f"ORDER BY st.dep_secs LIMIT ?",
            (stop["stop_id"], after_time, *service_ids, count)
        ).fetchall()
        return [{
            "route":     r["route_short_name"],
            "headsign":  r["trip_headsign"],
            "departure": f"{r['dep_secs']//3600:02d}:{(r['dep_secs']%3600)//60:02d}",
            "stop_code": stop_code,
        } for r in rows]
