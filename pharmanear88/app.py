import math
from flask import Flask, jsonify, render_template, request
import requests

app = Flask(__name__)

SERPAPI_KEY = (
    "6e07751de2550a29983fcfe68d6a868dd52c574206aaeae13795a0b9eed8b7bb"
)


def calculate_distance_meters(lat1, lon1, lat2, lon2):
    R = 6371000
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


@app.route("/api/pharmacies", methods=["GET"])
def get_pharmacies():
    try:
        user_lat = request.args.get("lat", type=float)
        user_lon = request.args.get("lon", type=float)
        search_query = request.args.get("query", type=str)

        url = "https://serpapi.com/search.json"

        # إذا قام المستخدم بإدخال اسم حي يدويًا
        if search_query:
            params = {
                "engine": "google_maps",
                "q": f"صيدلية في {search_query}",
                "hl": "ar",
                "api_key": SERPAPI_KEY,
            }
        # إذا تم استخدام الـ GPS
        elif user_lat is not None and user_lon is not None:
            params = {
                "engine": "google_maps",
                "q": "صيدلية",
                "ll": f"@{user_lat},{user_lon},18z",  # تركيز بقطر مباني مجاورة
                "hl": "ar",
                "api_key": SERPAPI_KEY,
            }
        else:
            return jsonify(
                {"status": "error", "message": "الرجاء توفير بيانات موقع صحيحة"}
            ), 400

        res = requests.get(url, params=params, timeout=15)
        data = res.json()

        pharmacies = []
        if "local_results" in data:
            for item in data["local_results"]:
                gps = item.get("gps_coordinates", {})
                p_lat = gps.get("latitude")
                p_lon = gps.get("longitude")

                dist_text = "غير محددة بدقة"
                dist_m = 999999

                if user_lat and user_lon and p_lat and p_lon:
                    dist_m = calculate_distance_meters(
                        user_lat, user_lon, float(p_lat), float(p_lon)
                    )
                    dist_text = (
                        f"{int(dist_m)} متر"
                        if dist_m < 1000
                        else f"{round(dist_m / 1000, 2)} كم"
                    )

                pharmacies.append(
                    {
                        "name": item.get("title", "صيدلية"),
                        "address": item.get("address", "عنوان قريب"),
                        "distance_meters": dist_m,
                        "distance_text": dist_text,
                        "phone": item.get("phone", "غير متوفر"),
                        "status": item.get(
                            "open_state", "معلومات العمل غير متوفرة"
                        ),
                    }
                )

        if user_lat and user_lon:
            pharmacies.sort(key=lambda x: x["distance_meters"])

        return jsonify(
            {"status": "success", "count": len(pharmacies), "data": pharmacies}
        )

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)