"""
PharmaNear — nearby-pharmacy lookup, as a native Vercel Python function.

WHY THIS IS WRITTEN WITHOUT FLASK
------------------------------------------------------------------------
Two different Flask-based setups (app.py at the root with a legacy
"builds"/"routes" vercel.json, then api/index.py with a "rewrites"
vercel.json) both produced 404s on every path except "/". Rather than guess
a third Flask configuration, this uses Vercel's most basic, zero-config
Python convention directly from their own documentation: a file at
api/<name>.py exporting a class called `handler` that extends
BaseHTTPRequestHandler is automatically deployed as a serverless function at
/api/<name> — no vercel.json, no WSGI adapter, no "builds" or "rewrites"
config to get wrong. This removes every layer of configuration we have
already tried and failed with.

This file is placed at api/pharmacy-search.py, so Vercel serves it at:
    /api/pharmacy-search

Local testing (no Vercel needed) is at the bottom of this file.
"""

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
SERPAPI_URL = "https://serpapi.com/search.json"
REQUEST_TIMEOUT_S = 15


def calculate_distance_meters(lat1, lon1, lat2, lon2):
    """Great-circle (Haversine) distance in meters between two coordinates."""
    R = 6371000
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def format_distance(meters):
    if meters < 1000:
        return f"{int(meters)} متر"
    return f"{round(meters / 1000, 2)} كم"


def fetch_pharmacies(lat, lon, area):
    """Core logic, framework-independent so it's easy to unit test directly
    (see the __main__ block below) without spinning up an HTTP server."""
    if not SERPAPI_KEY:
        return {"status": "error", "message": "مفتاح SERPAPI_KEY غير مضبوط على الخادم."}, 500

    has_coords = lat is not None and lon is not None

    if area:
        params = {"engine": "google_maps", "q": f"صيدلية في {area}", "hl": "ar", "api_key": SERPAPI_KEY}
    elif has_coords:
        params = {"engine": "google_maps", "q": "صيدلية", "ll": f"@{lat},{lon},15z", "hl": "ar", "api_key": SERPAPI_KEY}
    else:
        return {"status": "error", "message": "الرجاء تحديد موقعك أو إدخال اسم المنطقة."}, 400

    url = SERPAPI_URL + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError:
        return {"status": "error", "message": "تعذّر الاتصال بمزود البيانات."}, 502
    except (ValueError, TimeoutError):
        return {"status": "error", "message": "انتهت مهلة الاتصال بمزود البيانات."}, 504

    if isinstance(data, dict) and data.get("error"):
        return {"status": "error", "message": f"خطأ من مزود البيانات: {data['error']}"}, 502

    pharmacies = []
    for item in data.get("local_results", []):
        gps = item.get("gps_coordinates") or {}
        p_lat, p_lon = gps.get("latitude"), gps.get("longitude")

        distance_meters, distance_text = None, "غير محددة"
        if has_coords and p_lat is not None and p_lon is not None:
            distance_meters = calculate_distance_meters(lat, lon, float(p_lat), float(p_lon))
            distance_text = format_distance(distance_meters)

        pharmacies.append({
            "name": item.get("title") or "صيدلية",
            "address": item.get("address") or "عنوان غير مسجل",
            "latitude": p_lat,
            "longitude": p_lon,
            "distance_meters": distance_meters,
            "distance_text": distance_text,
            "phone": (item.get("phone") or "").strip(),
            "status": item.get("open_state") or "الحالة غير معروفة",
        })

    if has_coords:
        pharmacies.sort(key=lambda p: p["distance_meters"] if p["distance_meters"] is not None else float("inf"))

    return {"status": "success", "count": len(pharmacies), "data": pharmacies}, 200


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)

        def _float_param(name):
            raw = query.get(name, [None])[0]
            try:
                return float(raw) if raw not in (None, "") else None
            except ValueError:
                return None

        lat = _float_param("lat")
        lon = _float_param("lon")
        area = (query.get("query", [None])[0] or "").strip()

        try:
            body, status = fetch_pharmacies(lat, lon, area)
        except Exception as exc:  # last-resort safety net — never crash without JSON
            body, status = {"status": "error", "message": f"خطأ غير متوقع: {exc}"}, 500

        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


if __name__ == "__main__":
    # Quick local sanity check without needing Vercel or a real HTTP server:
    #     SERPAPI_KEY=xxx python api/pharmacy-search.py
    os.environ.setdefault("SERPAPI_KEY", "test")
    print(fetch_pharmacies(15.58, 32.53, None))
    print(fetch_pharmacies(None, None, "الرياض"))
    print(fetch_pharmacies(None, None, None))
    
