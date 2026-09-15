import math
from flask import Flask, jsonify, render_template, request
import requests

app = Flask(__name__)

# مفتاح SerpApi الخاص بك
SERPAPI_KEY = (
    "6e07751de2550a29983fcfe68d6a868dd52c574206aaeae13795a0b9eed8b7bb"
)


def calculate_distance(lat1, lon1, lat2, lon2):
    """حساب المسافة بدقة بين نقطتين بالـ GPS"""
    R = 6371
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = math.sin(dLat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(dLon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/pharmacies/nearest", methods=["GET"])
def get_nearest():
    try:
        user_lat = request.args.get("lat", type=float)
        user_lon = request.args.get("lon", type=float)

        if user_lat is None or user_lon is None:
            return jsonify(
                {"status": "error", "message": "لم يتم التقاط الـ GPS"}
            ), 400

        # الاستعلام عن نتائج جوجل مابس الحية عبر SerpApi
        url = "https://serpapi.com/search.json"
        params = {
            "engine": "google_maps",
            "q": "صيدلية",
            "ll": f"@{user_lat},{user_lon},14z",
            "google_domain": "google.com",
            "hl": "ar",
            "api_key": SERPAPI_KEY,
        }

        response = requests.get(url, params=params, timeout=12)
        data = response.json()

        pharmacies = []

        if "local_results" in data:
            for item in data["local_results"]:
                gps = item.get("gps_coordinates", {})
                p_lat = gps.get("latitude")
                p_lon = gps.get("longitude")

                if p_lat and p_lon:
                    dist = calculate_distance(
                        user_lat, user_lon, float(p_lat), float(p_lon)
                    )

                    pharmacies.append(
                        {
                            "id": item.get("place_id_search", ""),
                            "name": item.get("title", "صيدلية"),
                            "lat": float(p_lat),
                            "lon": float(p_lon),
                            "distance": round(dist, 2),
                            "phone": item.get("phone", "غير متوفر"),
                            "address": item.get("address", "عنوان محلي"),
                            "rating": item.get("rating", "غير مقيم"),
                            "open_state": item.get(
                                "open_state", "معلومات العمل غير متوفرة"
                            ),
                        }
                    )

        # ترتيب الصيدليات تلقائياً حسب الأقرب لموقع الـ GPS
        pharmacies.sort(key=lambda x: x["distance"])

        return jsonify(
            {"status": "success", "count": len(pharmacies), "data": pharmacies}
        )

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)