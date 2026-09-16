"""
PharmaNear — Flask backend.

Serves the single self-contained page (templates/index.html) and one API
endpoint that looks up nearby pharmacies via SerpAPI's Google Maps engine.
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

# تم تعيين المفتاح مباشرة بدلاً من البيئة لتجاوز إعدادات Vercel
SERPAPI_KEY = os.environ.get("SERPAPI_KEY") or "6e07751de2550a29983fcfe68d6a868dd52c574206aaeae13795a0b9eed8b7bb"
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


@app.route("/api/pharmacies", methods=["GET"])
def get_pharmacies():
    """Find nearby pharmacies."""
    if not SERPAPI_KEY:
        return jsonify({
            "status": "error",
            "message": "مفتاح SERPAPI_KEY غير مضبوط على الخادم.",
        }), 500

    user_lat = request.args.get("lat", type=float)
    user_lon = request.args.get("lon", type=float)
    search_query = (request.args.get("query", type=str) or "").strip()

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
            "phone": phone,
            "status": item.get("open_state") or "الحالة غير معروفة",
        })

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)