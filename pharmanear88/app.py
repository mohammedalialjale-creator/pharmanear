import math
from flask import Flask, jsonify, request
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


HTML_LAYOUT = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PharmaNear - بوابتك الذكية للوصول إلى الدواء</title>
    <style>
        * { box-sizing: border-box; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        body { background-color: #0b1528; color: #ffffff; margin: 0; padding: 0; text-align: center; }
        .hero { padding: 40px 20px; max-width: 800px; margin: auto; }
        h1 { font-size: 2.2rem; font-weight: bold; margin-bottom: 10px; color: #ffffff; }
        p.subtitle { color: #a0aec0; font-size: 1rem; margin-bottom: 25px; }
        .stats { display: flex; justify-content: space-around; margin: 25px 0; border-top: 1px solid rgba(255,255,255,0.1); border-bottom: 1px solid rgba(255,255,255,0.1); padding: 15px 0; }
        .stat-item h3 { margin: 0; font-size: 1.5rem; color: #2ecc71; }
        .stat-item p { margin: 4px 0 0; color: #a0aec0; font-size: 0.85rem; }
        .interactive-card { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 16px; padding: 25px; backdrop-filter: blur(10px); margin-top: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
        .btn-group { display: flex; flex-direction: column; gap: 12px; max-width: 500px; margin: auto; }
        .btn-gps { background: #27ae60; color: white; border: none; padding: 14px 20px; border-radius: 10px; font-size: 1.05rem; font-weight: bold; cursor: pointer; transition: 0.3s; }
        .btn-gps:hover { background: #219150; }
        .search-box { display: flex; gap: 10px; margin-top: 8px; }
        .search-input { flex: 1; padding: 12px 15px; border-radius: 8px; border: 1px solid #4a5568; background: #1a202c; color: #fff; font-size: 0.95rem; text-align: right; }
        .btn-search { background: #f1c40f; color: #000; border: none; padding: 12px 20px; border-radius: 8px; font-weight: bold; cursor: pointer; }
        #msg { margin-top: 15px; font-weight: bold; font-size: 1rem; }
        .results-container { margin-top: 20px; text-align: right; max-width: 600px; margin-left: auto; margin-right: auto; }
        .pharmacy-item { background: #1a2638; border-right: 4px solid #27ae60; padding: 12px; border-radius: 8px; margin-bottom: 10px; }
        .pharmacy-item h3 { margin: 0 0 6px 0; color: #2ecc71; }
        .pharmacy-item p { margin: 4px 0; color: #cbd5e0; font-size: 0.9rem; }
    </style>
</head>
<body>
<div class="hero">
    <h1>بوابتك الذكية للوصول إلى الدواء</h1>
    <p class="subtitle">ابحث عن دوائك، اعثر على أقرب صيدلية متوفر فيها الدواء أو تواصل مباشرة مع الصيدلي في ثوانٍ.</p>
    <div class="stats">
        <div class="stat-item"><h3>+120</h3><p>صيدلية مسجلة</p></div>
        <div class="stat-item"><h3>+4,000</h3><p>عملية بحث يومياً</p></div>
        <div class="stat-item"><h3>&lt; 10s</h3><p>متوسط وقت الاتصال</p></div>
    </div>
    <div class="interactive-card">
        <h2 style="margin-top: 0; color: #3498db; font-size: 1.3rem;">جرب PharmaNear الآن 🎯</h2>
        <div class="btn-group">
            <button class="btn-gps" onclick="findByGPS()">📍 تحديد موقعي الحالي والأقرب فوراً</button>
            <div class="search-box">
                <input type="text" id="areaInput" class="search-input" placeholder="أو اكتب اسم حلتك/شارعك (مثل: شرق النيل الفيحاء)">
                <button class="btn-search" onclick="findByArea()">بحث 🔍</button>
            </div>
        </div>
        <div id="msg"></div>
        <div id="list" class="results-container"></div>
    </div>
</div>
<script>
function findByGPS() {
    const msg = document.getElementById('msg');
    const list = document.getElementById('list');
    msg.style.color = '#f1c40f';
    msg.innerText = '⏳ جاري التقاط الـ GPS واستكشاف أقرب الصيدليات...';
    list.innerHTML = '';
    if (!navigator.geolocation) {
        msg.style.color = '#e74c3c';
        msg.innerText = 'خاصية الـ GPS غير مدعومة في متصفحك.';
        return;
    }
    navigator.geolocation.getCurrentPosition(
        (pos) => {
            fetch(`/api/pharmacies?lat=${pos.coords.latitude}&lon=${pos.coords.longitude}`)
            .then(res => res.json())
            .then(data => renderResults(data))
            .catch(() => showError('خطأ في الاتصال بالخادم.'));
        },
        () => showError('يرجى السماح بالوصول للـ GPS لتحديد موقعك.'),
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );
}
function findByArea() {
    const area = document.getElementById('areaInput').value.trim();
    if (!area) { alert('الرجاء أدخل اسم الحي أو المنطقة أولاً'); return; }
    const msg = document.getElementById('msg');
    const list = document.getElementById('list');
    msg.style.color = '#f1c40f';
    msg.innerText = `⏳ جاري البحث عن صيدليات في (${area})...`;
    list.innerHTML = '';
    fetch(`/api/pharmacies?query=${encodeURIComponent(area)}`)
    .then(res => res.json())
    .then(data => renderResults(data))
    .catch(() => showError('خطأ في الاتصال بالخادم.'));
}
function renderResults(data) {
    const msg = document.getElementById('msg');
    const list = document.getElementById('list');
    if (data.status === 'success' && data.data.length > 0) {
        msg.innerText = '';
        data.data.forEach(p => {
            list.innerHTML += `
                <div class="pharmacy-item">
                    <h3>${p.name}</h3>
                    <p>📍 <b>العنوان:</b> ${p.address}</p>
                    <p>📏 <b>المسافة:</b> ${p.distance_text}</p>
                    <p>📞 <b>الهاتف:</b> ${p.phone}</p>
                    <p>🕒 <b>الحالة:</b> ${p.status}</p>
                </div>
            `;
        });
    } else {
        msg.style.color = '#e74c3c';
        msg.innerText = 'لم يتم العثور على صيدليات في هذا النطاق.';
    }
}
function showError(text) {
    const msg = document.getElementById('msg');
    msg.style.color = '#e74c3c';
    msg.innerText = text;
}
</script>
</body>
</html>"""


@app.route("/")
def index():
    return HTML_LAYOUT


@app.route("/api/pharmacies", methods=["GET"])
def get_pharmacies():
    try:
        user_lat = request.args.get("lat", type=float)
        user_lon = request.args.get("lon", type=float)
        search_query = request.args.get("query", type=str)

        url = "https://serpapi.com/search.json"

        if search_query:
            params = {
                "engine": "google_maps",
                "q": f"صيدلية في {search_query}",
                "hl": "ar",
                "api_key": SERPAPI_KEY,
            }
        elif user_lat is not None and user_lon is not None:
            params = {
                "engine": "google_maps",
                "q": "صيدلية",
                "ll": f"@{user_lat},{user_lon},18z",
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
