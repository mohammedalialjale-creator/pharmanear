import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)


def fetch_overpass_pharmacies(lat, lon, radius=3000):
    overpass_url = "https://overpass-api.de/api/interpreter"
    query = f"""
    [out:json];
    (
      node["amenity"="pharmacy"](around:{radius},{lat},{lon});
      way["amenity"="pharmacy"](around:{radius},{lat},{lon});
    );
    out center;
    """
    response = requests.get(overpass_url, params={"data": query}, timeout=10)
    data = response.json()

    pharmacies = []
    for element in data.get("elements", []):
        tags = element.get("tags", {})
        p_lat = element.get("lat") or element.get("center", {}).get("lat")
        p_lon = element.get("lon") or element.get("center", {}).get("lon")

        pharmacies.append(
            {
                "id": element.get("id"),
                "name": tags.get("name", "صيدلية غير مسماة"),
                "lat": p_lat,
                "lon": p_lon,
                "phone": tags.get("phone")
                or tags.get("contact:phone")
                or tags.get("mobile"),
            }
        )
    return pharmacies


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/pharmacies/nearest", methods=["GET"])
def get_nearest():
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)

    if not lat or not lon:
        return jsonify({"error": "Latitude and Longitude are required"}), 400

    results = fetch_overpass_pharmacies(lat, lon)
    return jsonify({"status": "success", "data": results})


if __name__ == "__main__":
    app.run(debug=True)