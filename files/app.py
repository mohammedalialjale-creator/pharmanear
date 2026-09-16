"""
PharmaNear — Flask backend (Vercel Serverless entrypoint).

WHY THIS FILE LIVES AT api/index.py AND NOT app.py AT THE PROJECT ROOT
------------------------------------------------------------------------
Vercel's Python runtime auto-detects serverless functions from files placed
under an /api directory — this is the current, officially supported, and
most reliable way to deploy a Flask app on Vercel, with no ambiguous legacy
"builds"/"routes" configuration involved.

The previous setup (app.py at the project root + a legacy vercel.json
"builds"/"routes" block) depends on routing behavior that is not guaranteed
across every Vercel project/dashboard configuration. The symptom you saw —
"/" working while every other path returns Vercel's own generic
"This page could not be found" HTML (which is what breaks response.json()
on the frontend with "Unexpected token ... is not valid JSON") — is the
signature of requests being intercepted by Vercel's platform router *before*
they ever reach Python. No amount of fixing the JavaScript or the Flask
route logic can fix that, because the request never arrives.

This file replaces app.py entirely. Delete app.py from the project root —
do not keep both, to remove any ambiguity about which file Vercel builds.

Final project layout:
    api/index.py         <- this file
    templates/index.html
    static/               (optional; only used if you keep static assets)
    vercel.json
    requirements.txt

Local run (from the project root):
    pip install -r requirements.txt
    export SERPAPI_KEY="your_key_here"     # Windows: set SERPAPI_KEY=...
    python api/index.py
"""

import os
import math

import requests
from flask import Flask, jsonify, render_template, request

# This file lives at <project-root>/api/index.py — templates/ and static/
# live one level up, at the project root. Computing this explicitly (rather
# than relying on Flask's default, which assumes templates/ sits next to
# this file) is what makes the app work regardless of which directory
# Vercel's runtime happens to set as the working directory.
API_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(API_DIR)

app = Flask(
    __name__,
    template_folder=os.path.join(PROJECT_ROOT, "templates"),
    static_folder=os.path.join(PROJECT_ROOT, "static"),
)

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
SERPAPI_URL = "https://serpapi.com/search.json"
REQUEST_TIMEOUT_S = 15


# ---------------------------------------------------------------------------
# CORS — permissive, so this API can be called from a different origin later
# (a separate frontend, a mobile app, etc.) without any backend changes.
# Same-origin calls from this project's own page work with or without this.
# ---------------------------------------------------------------------------
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


# ---------------------------------------------------------------------------
# Crash safety nets — every response out of this app is guaranteed valid
# JSON when something goes wrong inside Flask itself (a genuinely missing
# route, an unhandled exception), so the frontend's JSON parsing never
# breaks on *this app's own* errors. This cannot protect against Vercel's
# platform-level 404 (see the note at the top of this file) — only against
# bugs inside this Python code.
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def handle_not_found(_error):
    return jsonify({"status": "error", "message": "المسار غير موجود."}), 404


@app.errorhandler(500)
def handle_server_error(_error):
    return jsonify({"status": "error", "message": "خطأ داخلي غير متوقع في الخادم."}), 500


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


@app.route("/pharmacy-search", methods=["GET", "OPTIONS"])
def get_pharmacies():
    """Find nearby pharmacies.

    Query params (one of the two modes is required):
      lat + lon  — the visitor's GPS coordinates; results are sorted nearest-first.
      query      — a district/area name typed manually, when GPS is unavailable.
    """
    if request.method == "OPTIONS":
        # CORS preflight — no body needed.
        return ("", 204)

    try:
        if not SERPAPI_KEY:
            return jsonify({
                "status": "error",
                "message": "مفتاح SERPAPI_KEY غير مضبوط على الخادم.",
            }), 500

        user_lat = request.args.get("lat", type=float)
        user_lon = request.args.get("lon", type=float)
        search_query = (request.args.get("query", type=str) or "").strip()

        # Compare against None explicitly — `if user_lat` would treat a
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

        # SerpAPI reports quota exhaustion and bad keys as a 200 response with
        # an "error" field. Without this check those failures would look
        # identical to "no pharmacies nearby".
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
                # Empty string (not a placeholder) so the frontend can
                # reliably decide whether to render a Call button at all.
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

    except Exception as exc:  # last-resort safety net — never let an
        # unexpected exception escape as a non-JSON error page.
        return jsonify({
            "status": "error",
            "message": f"خطأ غير متوقع: {exc}",
        }), 500


@app.route("/api/pharmacies", methods=["GET", "OPTIONS"])
def get_pharmacies_legacy_alias():
    """Kept only for backward compatibility with any cached page or bookmark
    still calling the old path. The frontend now calls /pharmacy-search."""
    return get_pharmacies()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
