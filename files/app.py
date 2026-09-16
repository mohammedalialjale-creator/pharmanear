"""
PharmaNear — Flask backend.

Serves the single self-contained page (templates/index.html) and one API
endpoint that looks up nearby pharmacies via SerpAPI's Google Maps engine.

IMPORTANT — why the endpoint is /pharmacy-search and NOT /api/pharmacies:
Vercel reserves the "/api/" URL prefix for its own Serverless Functions
auto-detection convention (a request to any path under /api/ is expected to
correspond to an actual function file at that exact location, e.g.
api/pharmacies.py). A custom catch-all route in vercel.json cannot reliably
override that reservation on every project configuration — so a Flask route
registered at "/api/pharmacies" can end up intercepted by Vercel's platform
router before the request ever reaches this app, returning Vercel's own
"This page could not be found" HTML page instead of this app's JSON. That
HTML, fed into response.json() on the frontend, is exactly what produces a
"Unexpected token '<'/'T' ... is not valid JSON" error — no amount of
frontend fixing solves it, because the request never reaches Python at all.
Keeping every custom route OUTSIDE the /api/ prefix sidesteps the ambiguity
entirely.

Local run:
    pip install -r requirements.txt
    export SERPAPI_KEY="your_key_here"     # Windows: set SERPAPI_KEY=...
    python app.py

The SerpAPI key is read ONLY from the environment — never hardcoded, so it
can't leak through the Git history. On Vercel, set it under
Settings → Environment Variables.
"""

import os
import math

import requests
from flask import Flask, jsonify, render_template, request

# Absolute paths so template/static lookup never depends on the working
# directory (which differs inside Vercel's serverless runtime).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
SERPAPI_URL = "https://serpapi.com/search.json"
REQUEST_TIMEOUT_S = 15


def calculate_distance_meters(lat1, lon1, lat2, lon2):
    """Great-circle (Haversine) distance in meters between two coordinates."""
    R = 6371000  # Earth's mean radius in meters
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def format_distance(meters):
    """Human-readable distance: meters under 1 km, kilometers above."""
    if meters < 1000:
        return f"{int(meters)} متر"
    return f"{round(meters / 1000, 2)} كم"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/pharmacy-search", methods=["GET"])
def get_pharmacies():
    """Find nearby pharmacies.

    Query params (one of the two modes is required):
      lat + lon  — the visitor's GPS coordinates; results are sorted nearest-first.
      query      — a district/area name typed manually, when GPS is unavailable.
    """
    if not SERPAPI_KEY:
        # Fail loudly and early rather than sending a keyless request that
        # would come back as a confusing empty result.
        return jsonify({
            "status": "error",
            "message": "مفتاح SERPAPI_KEY غير مضبوط على الخادم.",
        }), 500

    user_lat = request.args.get("lat", type=float)
    user_lon = request.args.get("lon", type=float)
    search_query = (request.args.get("query", type=str) or "").strip()

    # Note: compare against None explicitly — `if user_lat` would treat a
    # legitimate coordinate of 0.0 (equator / prime meridian) as missing.
    has_coords = user_lat is not None and user_lon is not None

    if search_query:
        params = {
            "engine": "google_maps",
            "q": f"صيدلية في {search_query}",
            "hl": "ar",
            "api_key": SERPAPI_KEY,
        }
    elif has_coords:
        params = {
            "engine": "google_maps",
            "q": "صيدلية",
            "ll": f"@{user_lat},{user_lon},15z",
            "hl": "ar",
            "api_key": SERPAPI_KEY,
        }
    else:
        return jsonify({
            "status": "error",
            "message": "الرجاء تحديد موقعك أو إدخال اسم المنطقة.",
        }), 400

    try:
        response = requests.get(SERPAPI_URL, params=params, timeout=REQUEST_TIMEOUT_S)
        data = response.json()
    except requests.Timeout:
        return jsonify({
            "status": "error",
            "message": "انتهت مهلة الاتصال بمزود البيانات. حاول مرة أخرى.",
        }), 504
    except (requests.RequestException, ValueError):
        return jsonify({
            "status": "error",
            "message": "تعذّر الاتصال بمزود البيانات.",
        }), 502

    # SerpAPI reports quota exhaustion and bad keys as a 200 response with an
    # "error" field. Without this check those failures would look identical to
    # "no pharmacies nearby" — silent and nearly impossible to debug.
    if isinstance(data, dict) and data.get("error"):
        return jsonify({
            "status": "error",
            "message": f"خطأ من مزود البيانات: {data['error']}",
        }), 502

    pharmacies = []
    for item in data.get("local_results", []):
        gps = item.get("gps_coordinates") or {}
        p_lat = gps.get("latitude")
        p_lon = gps.get("longitude")

        distance_meters = None
        distance_text = "غير محددة"

        if has_coords and p_lat is not None and p_lon is not None:
            distance_meters = calculate_distance_meters(
                user_lat, user_lon, float(p_lat), float(p_lon)
            )
            distance_text = format_distance(distance_meters)

        phone = (item.get("phone") or "").strip()

        pharmacies.append({
            "name": item.get("title") or "صيدلية",
            "address": item.get("address") or "عنوان غير مسجل",
            "latitude": p_lat,
            "longitude": p_lon,
            "distance_meters": distance_meters,
            "distance_text": distance_text,
            # Empty string (not a placeholder) so the frontend can reliably
            # decide whether to render a Call button at all.
            "phone": phone,
            "status": item.get("open_state") or "الحالة غير معروفة",
        })

    # Sort nearest-first; entries without a computed distance go last.
    if has_coords:
        pharmacies.sort(
            key=lambda p: p["distance_meters"]
            if p["distance_meters"] is not None
            else float("inf")
        )

    return jsonify({
        "status": "success",
        "count": len(pharmacies),
        "data": pharmacies,
    })


@app.route("/api/pharmacies", methods=["GET"])
def get_pharmacies_legacy_alias():
    """Kept only in case a cached page or bookmark still calls the old path.
    If Vercel's /api/ reservation is in fact the cause of the 404s, this
    route may still be unreachable in production — /pharmacy-search is the
    one the frontend actually calls now."""
    return get_pharmacies()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
