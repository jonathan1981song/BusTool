"""
app.py
------
Flask web application for Brisbane bus timetable lookup.
"""

import os
import socket
import threading
from datetime import date, datetime

from flask import Flask, render_template, request, jsonify

from bustool.api import GTFSData, _haversine_m

app = Flask(__name__)

_gtfs_data = None
_gtfs_ready = threading.Event()
_gtfs_error = None


def _preload_gtfs():
    global _gtfs_data, _gtfs_error
    try:
        _gtfs_data = GTFSData.load()
    except Exception as e:
        _gtfs_error = str(e)
    finally:
        _gtfs_ready.set()


if os.environ.get('WERKZEUG_RUN_MAIN') != 'false':
    threading.Thread(target=_preload_gtfs, daemon=True).start()


def get_gtfs() -> GTFSData:
    _gtfs_ready.wait()
    if _gtfs_error:
        raise RuntimeError(f'GTFS load failed: {_gtfs_error}')
    return _gtfs_data


def _current_secs() -> int:
    now = datetime.now()
    return now.hour * 3600 + now.minute * 60 + now.second


# ------------------------------------------------------------------ #
# Routes
# ------------------------------------------------------------------ #

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/status')
def status():
    return jsonify({'ready': _gtfs_ready.is_set(), 'error': _gtfs_error})


@app.route('/search_routes')
def search_routes():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])
    return jsonify(get_gtfs().search_routes(query, limit=10))


@app.route('/search_stops')
def search_stops_route():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    return jsonify(get_gtfs().search_stops(q, limit=10))


@app.route('/route/<route_id>')
def route_detail(route_id):
    gtfs = get_gtfs()
    route = gtfs.get_route(route_id)
    if not route:
        return render_template('error.html', message=f"Route {route_id} not found"), 404
    stops = gtfs.get_route_all_stops(route_id)
    return render_template('route_detail.html', route=route, stops=stops)


@app.route('/timetable')
def timetable():
    route_id = request.args.get('route_id', '')
    day_type  = request.args.get('day', 'weekday')
    stop_id   = request.args.get('stop_id', '')

    if not route_id:
        return render_template('error.html', message="No route specified"), 400

    gtfs = get_gtfs()
    route = gtfs.get_route(route_id)
    if not route:
        return render_template('error.html', message=f"Route {route_id} not found"), 404

    stop_name = ''
    if stop_id:
        stop = gtfs.get_stop_by_id(stop_id)
        if stop:
            stop_name = stop['stop_name']

    timetable_data = _build_timetable(gtfs, route_id, day_type, stop_id)

    return render_template('timetable.html',
                           route=route,
                           timetable=timetable_data,
                           day_type=day_type,
                           stop_id=stop_id,
                           stop_name=stop_name)


def _build_timetable(gtfs: GTFSData, route_id: str, day_type: str, stop_id: str = '') -> list[dict]:
    service_ids = gtfs.get_service_ids_for_day_type(day_type)
    if stop_id:
        entries = gtfs.get_timetable_at_stop(route_id, stop_id, service_ids)
        stop = gtfs.get_stop_by_id(stop_id)
        stop_name = stop['stop_name'] if stop else stop_id
        result = []
        for e in entries:
            times = sorted(e['times'])
            result.append({'stop_name': stop_name, 'headsign': e['headsign'], 'times': times})
        result.sort(key=lambda x: x['times'][0] if x['times'] else '99:99')
        return result
    else:
        entries = gtfs.get_timetable_origin(route_id, service_ids)
        for e in entries:
            e['times'].sort()
        entries.sort(key=lambda x: x['times'][0] if x['times'] else '99:99')
        return entries


@app.route('/next_bus')
def next_bus():
    route_id  = request.args.get('route_id', '')
    direction = request.args.get('direction', '').strip()
    if not route_id:
        return render_template('error.html', message="请输入路线编号"), 400
    gtfs = get_gtfs()
    route = gtfs.get_route(route_id)
    if not route:
        return render_template('error.html', message=f"未找到路线 {route_id}"), 404
    departures = _get_next_departures(gtfs, route_id, direction)
    return render_template('next_bus.html', route=route, departures=departures, direction=direction)


@app.route('/next_bus_times')
def next_bus_times():
    route_id  = request.args.get('route_id', '')
    direction = request.args.get('direction', '').strip()
    if not route_id:
        return jsonify([])
    return jsonify(_get_next_departures(get_gtfs(), route_id, direction))


@app.route('/direction')
def direction_detail():
    route_id  = request.args.get('route_id', '')
    direction = request.args.get('direction', '').strip()
    stop_id   = request.args.get('stop_id', '')

    if not route_id:
        return render_template('error.html', message="请输入路线编号"), 400

    gtfs = get_gtfs()
    route = gtfs.get_route(route_id)
    if not route:
        return render_template('error.html', message=f"未找到路线 {route_id}"), 404

    departures = _get_next_departures(gtfs, route_id, direction)
    stops = gtfs.get_direction_stops(route_id, direction)

    stop_name = ''
    if stop_id:
        stop = gtfs.get_stop_by_id(stop_id)
        if stop:
            stop_name = stop['stop_name']

    return render_template('direction.html',
                           route=route,
                           departures=departures,
                           stops=stops,
                           direction=direction,
                           stop_id=stop_id,
                           stop_name=stop_name)


def _get_next_departures(gtfs: GTFSData, route_id: str, direction: str = '') -> list[dict]:
    service_ids = gtfs.get_active_service_ids(date.today())
    after_secs  = _current_secs()
    rows = gtfs.get_next_departures(route_id, service_ids, after_secs, direction)
    result = []
    seen: set = set()
    for r in rows:
        key = f"{r['stop_id']}_{r['departure_time']}"
        if key in seen:
            continue
        seen.add(key)
        dep = r['dep_secs']
        result.append({
            'stop_name': r['stop_name'],
            'headsign':  r['trip_headsign'],
            'departure': f"{(dep // 3600) % 24:02d}:{(dep % 3600) // 60:02d}",
            'stop_code': r['stop_code'],
        })
    return result[:20]


@app.route('/route_stops')
def route_stops():
    route_id = request.args.get('route_id', '')
    if not route_id:
        return jsonify({'stops': []})
    stops = get_gtfs().get_route_stops_with_headsign(route_id)
    return jsonify({'stops': stops})


@app.route('/nearby_routes')
def nearby_routes():
    try:
        lat = float(request.args.get('lat', ''))
        lon = float(request.args.get('lon', ''))
    except ValueError:
        return jsonify({'error': 'Invalid coordinates'}), 400

    radius_m = float(request.args.get('radius', 500))
    gtfs = get_gtfs()

    today      = date.today()
    now_secs   = _current_secs()

    nearby = gtfs.get_stops_near(lat, lon, radius_m)
    if not nearby:
        return jsonify({'routes': []})

    dist_map = {stop_id: dist for stop_id, dist in nearby}
    stop_ids  = list(dist_map.keys())

    service_ids = gtfs.get_active_service_ids(today)

    # For each route: find nearest stop with earliest next departure
    departures = gtfs.get_departures_for_stops(stop_ids, service_ids, now_secs)
    route_best: dict = {}  # route_id -> (dep_secs, stop_id, dist, headsign, short, long)
    for r in departures:
        rid = r['route_id']
        if rid not in route_best or r['dep_secs'] < route_best[rid][0]:
            route_best[rid] = (
                r['dep_secs'], r['stop_id'], dist_map[r['stop_id']],
                r['trip_headsign'], r['route_short_name'], r['route_long_name'],
            )

    # No-service routes (serve the stops but no bus today)
    all_routes = gtfs.get_all_routes_at_stops(stop_ids)
    route_nearest: dict = {}  # route_id -> (dist, stop_id, short, long)
    for r in all_routes:
        rid = r['route_id']
        if rid not in route_best:
            d = dist_map[r['stop_id']]
            if rid not in route_nearest or d < route_nearest[rid][0]:
                route_nearest[rid] = (d, r['stop_id'], r['route_short_name'], r['route_long_name'])

    # Build raw list
    raw = []
    for rid, (dep_secs, stop_id, dist, headsign, short, long) in route_best.items():
        stop = gtfs.get_stop_by_id(stop_id)
        raw.append({
            'route_id':          rid,
            'route_short_name':  short,
            'route_long_name':   long,
            'nearest_stop_id':   stop_id,
            'nearest_stop_name': stop['stop_name'] if stop else stop_id,
            'distance_m':        round(dist),
            'next_departure':    f"{(dep_secs // 3600) % 24:02d}:{(dep_secs % 3600) // 60:02d}",
            'next_headsign':     headsign,
            '_sort':             dep_secs,
        })
    for rid, (dist, stop_id, short, long) in route_nearest.items():
        stop = gtfs.get_stop_by_id(stop_id)
        raw.append({
            'route_id':          rid,
            'route_short_name':  short,
            'route_long_name':   long,
            'nearest_stop_id':   stop_id,
            'nearest_stop_name': stop['stop_name'] if stop else stop_id,
            'distance_m':        round(dist),
            'next_departure':    None,
            'next_headsign':     '',
            '_sort':             999999,
        })

    # Deduplicate by route_short_name, keep earliest departure
    by_name: dict = {}
    for r in raw:
        name = r['route_short_name']
        if name not in by_name or r['_sort'] < by_name[name]['_sort']:
            by_name[name] = r

    results = sorted(by_name.values(), key=lambda x: (x['_sort'], x['distance_m']))
    for r in results:
        del r['_sort']

    return jsonify({'routes': results[:30]})


if __name__ == '__main__':
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = 'localhost'
    print(f'\n  Open on this PC:    http://localhost:5000')
    print(f'  Open on your phone: http://{local_ip}:5000\n')
    app.run(debug=False, host='0.0.0.0', port=5000)
