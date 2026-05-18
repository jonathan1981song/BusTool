"""
app.py
------
Flask web application for Brisbane bus timetable lookup.
Provides a mobile-friendly, elderly-accessible interface with large text and buttons.

Usage:
    python app.py

The app will be available at http://localhost:5000
"""

import math
import os
import socket
import threading

from flask import Flask, render_template, request, jsonify

from bustool.api import GTFSData

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


# Start loading immediately — avoids a long freeze on the first user request.
# Guard against Flask's debug reloader launching the module twice.
if os.environ.get('WERKZEUG_RUN_MAIN') != 'false':
    threading.Thread(target=_preload_gtfs, daemon=True).start()


def get_gtfs():
    """Block until GTFS data is ready, then return it."""
    _gtfs_ready.wait()
    if _gtfs_error:
        raise RuntimeError(f'GTFS load failed: {_gtfs_error}')
    return _gtfs_data


@app.route('/')
def index():
    """Homepage with route search box."""
    return render_template('index.html')


@app.route('/search_routes', methods=['GET'])
def search_routes():
    """Search for bus routes by number or name."""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])
    
    gtfs = get_gtfs()
    routes = gtfs.search_routes(query, limit=10)
    return jsonify(routes)


@app.route('/route/<route_id>')
def route_detail(route_id):
    """Show route information and stops."""
    gtfs = get_gtfs()
    
    # Find the route
    route = gtfs.routes.get(route_id)
    if not route:
        return render_template('error.html', message=f"Route {route_id} not found"), 404
    
    # Find all stops served by this route
    stops = get_route_stops(gtfs, route_id)
    
    return render_template('route_detail.html', route=route, stops=stops)


def get_route_stops(gtfs, route_id):
    """Get all stops served by a route in order.
    
    Follows the GTFS relationship:
    routes.txt -> trips.txt -> stop_times.txt -> stops.txt
    """
    # Step 1: Find all trip_ids for this route
    trip_ids = {t['trip_id'] for t in gtfs.trips_by_route.get(route_id, [])}
    
    if not trip_ids:
        return []
    
    # Step 2: Find all stops served by these trips using the trip index
    stop_sequences = {}
    for trip_id in trip_ids:
        for st in gtfs.stop_times_by_trip.get(trip_id, []):
            stop_id = st['stop_id']
            seq = st['stop_sequence']
            if stop_id not in stop_sequences or seq < stop_sequences[stop_id]:
                stop_sequences[stop_id] = seq
    
    # Step 3: Get stop details from stops.txt
    stops = []
    for stop_id, seq in sorted(stop_sequences.items(), key=lambda x: x[1]):
        if stop_id in gtfs.stops_by_id:
            stop = gtfs.stops_by_id[stop_id]
            stops.append({
                'stop_code': stop['stop_code'],
                'stop_name': stop['stop_name'],
                'sequence': seq
            })
    
    return stops


@app.route('/timetable')
def timetable():
    """Show timetable for a route, optionally filtered to a specific stop."""
    route_id = request.args.get('route_id', '')
    day_type = request.args.get('day', 'weekday')
    stop_id = request.args.get('stop_id', '')

    if not route_id:
        return render_template('error.html', message="No route specified"), 400

    gtfs = get_gtfs()

    route = gtfs.routes.get(route_id)
    if not route:
        return render_template('error.html', message=f"Route {route_id} not found"), 404

    stop_name = ''
    if stop_id and stop_id in gtfs.stops_by_id:
        stop_name = gtfs.stops_by_id[stop_id]['stop_name']

    timetable_data = get_timetable_for_route(gtfs, route_id, day_type, stop_id)

    return render_template('timetable.html',
                           route=route,
                           timetable=timetable_data,
                           day_type=day_type,
                           stop_id=stop_id,
                           stop_name=stop_name)


def get_timetable_for_route(gtfs, route_id, day_type, stop_id=None):
    """Get timetable data for a route on a specific day type.

    If stop_id is given, returns all departure times from that stop grouped
    by direction — this is the "current location" timetable.

    Otherwise, returns departure times from each direction's origin stop.
    """
    from collections import defaultdict

    weekday_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']
    service_ids = set()
    for sid, cal in gtfs.calendar.items():
        if day_type == 'weekday':
            if any(cal.get(d) == '1' for d in weekday_days):
                service_ids.add(sid)
        elif day_type == 'saturday':
            if cal.get('saturday') == '1':
                service_ids.add(sid)
        elif day_type == 'sunday':
            if cal.get('sunday') == '1':
                service_ids.add(sid)

    trips = [t for t in gtfs.trips_by_route.get(route_id, [])
             if t['service_id'] in service_ids]

    if not trips:
        return []

    if stop_id:
        # Show all departure times from the user's specific stop, grouped by direction
        stop_name = gtfs.stops_by_id.get(stop_id, {}).get('stop_name', stop_id)
        headsign_times = defaultdict(list)
        for trip in trips:
            trip_id = trip['trip_id']
            headsign = trip.get('trip_headsign', '')
            for st in gtfs.stop_times_by_trip.get(trip_id, []):
                if st['stop_id'] == stop_id:
                    headsign_times[headsign].append(st['departure_time'])

        timetable = []
        for headsign, times in headsign_times.items():
            times.sort()
            timetable.append({
                'stop_name': stop_name,
                'headsign': headsign,
                'times': times,
            })
        timetable.sort(key=lambda x: x['times'][0] if x['times'] else '99:99')
        return timetable

    # No stop given — show departure times from each direction's origin stop
    direction_data = defaultdict(lambda: defaultdict(list))  # headsign -> stop_id -> [times]
    for trip in trips:
        trip_id = trip['trip_id']
        headsign = trip.get('trip_headsign', '')
        sts = gtfs.stop_times_by_trip.get(trip_id, [])
        if not sts:
            continue
        first_st = min(sts, key=lambda x: x['stop_sequence'])
        direction_data[headsign][first_st['stop_id']].append(first_st['departure_time'])

    timetable = []
    for headsign, stops in direction_data.items():
        for sid, times in stops.items():
            if sid not in gtfs.stops_by_id:
                continue
            stop = gtfs.stops_by_id[sid]
            times.sort()
            timetable.append({
                'stop_name': stop['stop_name'],
                'headsign': headsign,
                'times': times,
            })

    timetable.sort(key=lambda x: x['times'][0] if x['times'] else '99:99')
    return timetable


@app.route('/next_bus')
def next_bus():
    """Show next departures for a route and direction."""
    route_id = request.args.get('route_id', '')
    direction = request.args.get('direction', '').strip()
    
    if not route_id:
        return render_template('error.html', message="请输入路线编号"), 400
    
    gtfs = get_gtfs()
    
    # Find the route
    route = gtfs.routes.get(route_id)
    if not route:
        return render_template('error.html', message=f"未找到路线 {route_id}"), 404
    
    # Get next departures
    departures = get_next_departures(gtfs, route_id, direction)
    
    return render_template('next_bus.html', 
                          route=route, 
                          departures=departures, 
                          direction=direction)


def get_next_departures(gtfs, route_id, direction=None):
    """Get next departures for a route from all stops.
    
    Uses current Brisbane time to find upcoming services.
    Optimized: Only processes stops that are served by this route.
    """
    from datetime import date, datetime
    
    # Get current date and time
    now = datetime.now()
    today = date.today()
    current_time_secs = now.hour * 3600 + now.minute * 60 + now.second
    
    # Find service_ids running today
    service_ids_today = set()
    for sid, cal in gtfs.calendar.items():
        if gtfs._is_service_running(sid, today):
            service_ids_today.add(sid)
    
    # Find trips for this route that run today
    trip_ids_today = set()
    trip_headsigns = {}
    for trip in gtfs.trips_by_route.get(route_id, []):
        if trip['service_id'] not in service_ids_today:
            continue
        if direction and direction.lower() not in trip.get('trip_headsign', '').lower():
            continue
        trip_ids_today.add(trip['trip_id'])
        trip_headsigns[trip['trip_id']] = trip.get('trip_headsign', '')
    
    if not trip_ids_today:
        return []
    
    # Collect departures using the trip index for direct lookup
    departures = []
    seen = set()

    for trip_id in trip_ids_today:
        headsign = trip_headsigns.get(trip_id, '')
        for st in gtfs.stop_times_by_trip.get(trip_id, []):
            stop_id = st['stop_id']
            dep_time = st['departure_time']
            
            # Parse departure time
            time_parts = dep_time.split(':')
            dep_secs = int(time_parts[0]) * 3600 + int(time_parts[1]) * 60 + int(time_parts[2])
            
            # Only show future departures
            if dep_secs <= current_time_secs:
                continue
            
            # Avoid duplicates
            key = f"{stop_id}_{dep_time}"
            if key in seen:
                continue
            seen.add(key)
            
            # Get stop info
            if stop_id not in gtfs.stops_by_id:
                continue
            
            stop = gtfs.stops_by_id[stop_id]
            
            # Format time
            h = (dep_secs // 3600) % 24
            m = (dep_secs % 3600) // 60
            
            departures.append({
                'stop_name': stop['stop_name'],
                'headsign': headsign,
                'departure': f"{h:02d}:{m:02d}",
                'stop_code': stop['stop_code'],
                '_sort_key': dep_secs
            })
    
    # Sort by departure time and limit
    departures.sort(key=lambda x: x['_sort_key'])
    
    # Remove sort key before returning
    for d in departures:
        del d['_sort_key']
    
    return departures[:20]


@app.route('/route_stops')
def route_stops():
    """Get all stops for a route with headsign and coordinates."""
    route_id = request.args.get('route_id', '')
    if not route_id:
        return jsonify({'stops': []})
    
    gtfs = get_gtfs()
    
    # Find all trips for this route
    trip_headsigns = {t['trip_id']: t.get('trip_headsign', '')
                      for t in gtfs.trips_by_route.get(route_id, [])}
    
    # Find all stops with their headsigns using the trip index
    stops_dict = {}
    for trip_id, headsign in trip_headsigns.items():
        for st in gtfs.stop_times_by_trip.get(trip_id, []):
            stop_id = st['stop_id']
            if stop_id not in stops_dict and stop_id in gtfs.stops_by_id:
                stop = gtfs.stops_by_id[stop_id]
                stops_dict[stop_id] = {
                    'stop_id': stop_id,
                    'stop_name': stop['stop_name'],
                    'stop_lat': stop.get('stop_lat', ''),
                    'stop_lon': stop.get('stop_lon', ''),
                    'headsign': headsign,
                }
    
    stops = list(stops_dict.values())
    return jsonify({'stops': stops})


@app.route('/next_bus_times')
def next_bus_times():
    """Get next bus times for a route and direction."""
    route_id = request.args.get('route_id', '')
    direction = request.args.get('direction', '').strip()
    
    if not route_id:
        return jsonify([])
    
    gtfs = get_gtfs()
    departures = get_next_departures(gtfs, route_id, direction)
    return jsonify(departures)


@app.route('/direction')
def direction_detail():
    """Show direction detail page with upcoming services and stops."""
    route_id = request.args.get('route_id', '')
    direction = request.args.get('direction', '').strip()
    stop_id = request.args.get('stop_id', '')

    if not route_id:
        return render_template('error.html', message="请输入路线编号"), 400

    gtfs = get_gtfs()

    route = gtfs.routes.get(route_id)
    if not route:
        return render_template('error.html', message=f"未找到路线 {route_id}"), 404

    departures = get_next_departures(gtfs, route_id, direction)
    stops = get_direction_stops(gtfs, route_id, direction)

    stop_name = ''
    if stop_id and stop_id in gtfs.stops_by_id:
        stop_name = gtfs.stops_by_id[stop_id]['stop_name']

    return render_template('direction.html',
                           route=route,
                           departures=departures,
                           stops=stops,
                           direction=direction,
                           stop_id=stop_id,
                           stop_name=stop_name)


def get_direction_stops(gtfs, route_id, direction):
    """Get all stops for a specific direction of a route."""
    # Find trips for this route and direction
    trip_ids = set()
    for trip in gtfs.trips_by_route.get(route_id, []):
        headsign = trip.get('trip_headsign', '')
        if direction.lower() in headsign.lower() or headsign.lower() in direction.lower():
            trip_ids.add(trip['trip_id'])
    
    if not trip_ids:
        return []
    
    # Find stops for these trips using the trip index
    stop_sequences = {}
    for trip_id in trip_ids:
        for st in gtfs.stop_times_by_trip.get(trip_id, []):
            stop_id = st['stop_id']
            seq = st['stop_sequence']
            if stop_id not in stop_sequences or seq < stop_sequences[stop_id]:
                stop_sequences[stop_id] = seq
    
    # Get stop details
    stops = []
    for stop_id, seq in sorted(stop_sequences.items(), key=lambda x: x[1]):
        if stop_id in gtfs.stops_by_id:
            stop = gtfs.stops_by_id[stop_id]
            stops.append({
                'stop_id': stop_id,
                'stop_name': stop['stop_name'],
                'sequence': seq,
            })

    return stops


def _haversine_m(lat1, lon1, lat2, lon2):
    """Return the distance in metres between two lat/lon points."""
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@app.route('/nearby_routes')
def nearby_routes():
    """Return all routes within radius_m of a lat/lon, sorted by next departure.

    For each route the reported stop is the one from which the next bus actually
    departs — so it is guaranteed to appear in the direction page's stop list
    and the current-stop highlight will always work.
    """
    try:
        lat = float(request.args.get('lat', ''))
        lon = float(request.args.get('lon', ''))
    except ValueError:
        return jsonify({'error': 'Invalid coordinates'}), 400

    radius_m = float(request.args.get('radius', 1000))
    gtfs = get_gtfs()

    from datetime import date, datetime
    today = date.today()
    now = datetime.now()
    current_secs = now.hour * 3600 + now.minute * 60 + now.second

    # Collect nearby stops with their distances
    nearby_stops = []
    for stop_id, stop in gtfs.stops_by_id.items():
        try:
            slat, slon = float(stop['stop_lat']), float(stop['stop_lon'])
        except (ValueError, TypeError):
            continue
        dist = _haversine_m(lat, lon, slat, slon)
        if dist <= radius_m:
            nearby_stops.append((stop_id, dist))

    if not nearby_stops:
        return jsonify({'routes': []})

    service_ids_today = {sid for sid in gtfs.calendar
                         if gtfs._is_service_running(sid, today)}

    # For each route, find the nearby stop with the earliest next departure.
    # Using stop_times_by_stop means the stop_id we keep is the exact stop
    # the bus departs from — guaranteed to appear in the direction stop list.
    route_best = {}  # route_id -> (next_secs, stop_id, dist_m, headsign)
    for stop_id, dist in nearby_stops:
        for st in gtfs.stop_times_by_stop.get(stop_id, []):
            trip = gtfs.trips.get(st['trip_id'])
            if not trip or trip['service_id'] not in service_ids_today:
                continue
            parts = st['departure_time'].split(':')
            dep = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            if dep <= current_secs:
                continue
            route_id = trip['route_id']
            if route_id not in route_best or dep < route_best[route_id][0]:
                route_best[route_id] = (dep, stop_id, dist, trip.get('trip_headsign', ''))

    # Also collect routes with no upcoming service today (show at bottom)
    route_nearest = {}  # route_id -> (dist, stop_id) for no-service routes
    for stop_id, dist in nearby_stops:
        for route_id in gtfs.routes_by_stop.get(stop_id, set()):
            if route_id not in route_best:
                if route_id not in route_nearest or dist < route_nearest[route_id][0]:
                    route_nearest[route_id] = (dist, stop_id)

    # Build result list
    raw = []
    seen_ids = set(route_best.keys()) | set(route_nearest.keys())
    for route_id in seen_ids:
        route = gtfs.routes.get(route_id)
        if not route:
            continue
        if route_id in route_best:
            next_secs, stop_id, dist, headsign = route_best[route_id]
            h = (next_secs // 3600) % 24
            m = (next_secs % 3600) // 60
            raw.append({
                'route_id': route_id,
                'route_short_name': route['route_short_name'],
                'route_long_name': route['route_long_name'],
                'nearest_stop_id': stop_id,
                'nearest_stop_name': gtfs.stops_by_id[stop_id]['stop_name'],
                'distance_m': round(dist),
                'next_departure': f'{h:02d}:{m:02d}',
                'next_headsign': headsign,
                '_sort': next_secs,
            })
        else:
            dist, stop_id = route_nearest[route_id]
            raw.append({
                'route_id': route_id,
                'route_short_name': route['route_short_name'],
                'route_long_name': route['route_long_name'],
                'nearest_stop_id': stop_id,
                'nearest_stop_name': gtfs.stops_by_id[stop_id]['stop_name'],
                'distance_m': round(dist),
                'next_departure': None,
                'next_headsign': '',
                '_sort': 999999,
            })

    # Deduplicate by route_short_name — keep entry with earliest next departure
    by_name = {}
    for r in raw:
        name = r['route_short_name']
        if name not in by_name or r['_sort'] < by_name[name]['_sort']:
            by_name[name] = r

    results = sorted(by_name.values(), key=lambda x: (x['_sort'], x['distance_m']))
    for r in results:
        del r['_sort']

    return jsonify({'routes': results[:30]})


@app.route('/status')
def status():
    """Return whether GTFS data has finished loading."""
    return jsonify({'ready': _gtfs_ready.is_set(), 'error': _gtfs_error})


@app.route('/search_stops')
def search_stops_route():
    """Search stops by name for the manual location fallback."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    gtfs = get_gtfs()
    stops = gtfs.search_stops(q, limit=10)
    return jsonify(stops)


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