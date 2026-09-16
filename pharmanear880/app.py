"""
PharmaNear — Flask backend (Vercel-ready).

المسارات:
    /pharmacy-search              GET
    /pharmacies                   POST
    /pharmacies/<id>              PUT
    /pharmacies/<id>/medicines    POST
    /medicines/<id>               PUT
    /medicines/<id>               DELETE

لا نستخدم بادئة /api/ لأن Vercel يحجزها ويرجع HTML بدل JSON.
"""

import os
import math
import uuid
import threading

import requests
from flask import Flask, jsonify, render_template, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
SERPAPI_URL = "https://serpapi.com/search.json"
REQUEST_TIMEOUT_S = 15

_LOCK = threading.Lock()
_PHARMACIES = {}


def calculate_distance_meters(lat1, lon1, lat2, lon2):
    R = 6371000
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
    if meters < 1000:
        return f"{int(meters)} متر"
    return f"{round(meters / 1000, 2)} كم"


def json_error(message, status=400):
    return jsonify({"status": "error", "message": message}), status


@app.errorhandler(404)
def _not_found(e):
    return json_error("المسار غير موجود على الخادم.", 404)


@app.errorhandler(405)
def _method_not_allowed(e):
    return json_error("طريقة الطلب غير مسموحة لهذا المسار.", 405)


@app.errorhandler(500)
def _server_error(e):
    return json_error("خطأ داخلي في الخادم.", 500)


@app.errorhandler(Exception)
def _unhandled(e):
    app.logger.exception("Unhandled error: %s", e)
    return json_error("حدث خطأ غير متوقع على الخادم.", 500)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/pharmacy-search", methods=["GET"])
def get_pharmacies():
    if not SERPAPI_KEY:
        return json_error("مفتاح SERPAPI_KEY غير مضبوط على الخادم.", 500)

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
        return json_error("الرجاء تحديد موقعك أو إدخال اسم المنطقة.", 400)

    try:
        response = requests.get(SERPAPI_URL, params=params, timeout=REQUEST_TIMEOUT_S)
        data = response.json()
    except requests.Timeout:
        return json_error("انتهت مهلة الاتصال بمزود البيانات. حاول مرة أخرى.", 504)
    except (requests.RequestException, ValueError):
        return json_error("تعذّر الاتصال بمزود البيانات.", 502)

    if isinstance(data, dict) and data.get("error"):
        return json_error(f"خطأ من مزود البيانات: {data['error']}", 502)

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


@app.route("/pharmacies", methods=["POST"])
def create_pharmacy():
    body = request.get_json(silent=True) or {}
    name = (body.get("name_ar") or body.get("name_en") or "").strip()
    if not name:
        return json_error("اسم الصيدلية مطلوب.", 400)

    pid = str(uuid.uuid4())
    record = {
        "id": pid,
        "name_ar": body.get("name_ar", name),
        "name_en": body.get("name_en", name),
        "address_ar": body.get("address_ar", ""),
        "address_en": body.get("address_en", ""),
        "latitude": body.get("latitude"),
        "longitude": body.get("longitude"),
        "phone": body.get("phone", ""),
        "hours": body.get("hours", ""),
        "status": body.get("status", "closed"),
        "medicines": [],
    }
    with _LOCK:
        _PHARMACIES[pid] = record

    return jsonify(record), 201


@app.route("/pharmacies/<pid>", methods=["PUT"])
def update_pharmacy(pid):
    body = request.get_json(silent=True) or {}
    with _LOCK:
        rec = _PHARMACIES.get(pid)
        if not rec:
            return json_error("الصيدلية غير موجودة.", 404)
        for key in ("name_ar", "name_en", "address_ar", "address_en",
                    "phone", "hours", "status", "latitude", "longitude"):
            if key in body:
                rec[key] = body[key]
    return jsonify(rec)


@app.route("/pharmacies/<pid>/medicines", methods=["POST"])
def add_medicine(pid):
    body = request.get_json(silent=True) or {}
    name = (body.get("name_ar") or body.get("name_en") or "").strip()
    if not name:
        return json_error("اسم الدواء مطلوب.", 400)

    with _LOCK:
        rec = _PHARMACIES.get(pid)
        if not rec:
            return json_error("الصيدلية غير موجودة.", 404)

        mid = str(uuid.uuid4())
        med = {
            "id": mid,
            "name_ar": body.get("name_ar", name),
            "name_en": body.get("name_en", name),
            "form_ar": body.get("form_ar", ""),
            "form_en": body.get("form_en", ""),
            "price": body.get("price", 0),
            "availability": body.get("availability", "in_stock"),
        }
        rec["medicines"].append(med)

    return jsonify(med), 201


@app.route("/medicines/<mid>", methods=["PUT"])
def update_medicine(mid):
    body = request.get_json(silent=True) or {}
    with _LOCK:
        for rec in _PHARMACIES.values():
            for med in rec["medicines"]:
                if med["id"] == mid:
                    for key in ("name_ar", "name_en", "form_ar", "form_en",
                                "price", "availability"):
                        if key in body:
                            med[key] = body[key]
                    return jsonify(med)
    return json_error("الدواء غير موجود.", 404)


@app.route("/medicines/<mid>", methods=["DELETE"])
def delete_medicine(mid):
    with _LOCK:
        for rec in _PHARMACIES.values():
            before = len(rec["medicines"])
            rec["medicines"] = [m for m in rec["medicines"] if m["id"] != mid]
            if len(rec["medicines"]) < before:
                return jsonify({"status": "success"})
    return json_error("الدواء غير موجود.", 404)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)