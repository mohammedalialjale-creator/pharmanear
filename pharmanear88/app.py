"""
PharmaNear — Flask backend.

Structure:
  app.py         — application factory, routes, API endpoints
  models.py      — SQLAlchemy models (Pharmacy, Medicine)
  extensions.py  — shared `db` instance
  osm_service.py — live pharmacy lookup via the Overpass API (OpenStreetMap)
  seed.py        — mock data + seeding logic (used for local/manual pharmacies)
  templates/     — Jinja templates (index.html)
  static/        — CSS + JS served to the browser

/api/pharmacies/nearest now finds real, live pharmacies from OpenStreetMap
within a radius of the user's GPS coordinates (via osm_service.py), computes
exact distance with geopy's geodesic formula, and sorts nearest-first. Each
OSM result is mirrored into the local `pharmacies` table (keyed by osm_id) —
that local row is what a pharmacist attaches medicines/stock/hours to later,
so OSM stays the source of truth for "does this pharmacy exist and where"
while the local DB owns everything editable.

Local run:
    pip install -r requirements.txt
    flask --app app seed-db     # optional — seeds a few manual demo pharmacies
    flask --app app run --debug

Switching from SQLite to Supabase/Postgres later: just set the
DATABASE_URL environment variable to your Postgres connection string
(e.g. the one Supabase gives you) — nothing else in this file needs to
change, since the models are plain SQLAlchemy.
"""

import os

from flask import Flask, render_template, request, jsonify
from geopy.distance import geodesic
from sqlalchemy import inspect, text

from extensions import db
from models import Pharmacy, Medicine
from osm_service import fetch_nearby_pharmacies
from seed import seed_database

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def create_app():
    app = Flask(__name__)

    # On Vercel's serverless filesystem only /tmp is writable, and it's wiped
    # between cold starts — fine for a demo, but for real persistence set
    # DATABASE_URL to a Postgres/Supabase connection string instead.
    if os.environ.get("VERCEL"):
        default_sqlite_path = "/tmp/pharmanear.db"
    else:
        default_sqlite_path = os.path.join(BASE_DIR, "pharmanear.db")

    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", f"sqlite:///{default_sqlite_path}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()
        _ensure_schema_upgrades()  # add new columns to an older local DB, if needed
        seed_database()  # no-op if the database already has data

    register_page_routes(app)
    register_api_routes(app)
    register_cli(app)

    return app


def _ensure_schema_upgrades():
    """Add columns introduced after a DB file already exists.

    Flask-SQLAlchemy's create_all() only creates missing *tables*, not
    missing *columns* on tables that already exist — so an older local
    pharmanear.db (from before the osm_id/source columns were added) would
    otherwise break. This is a lightweight stand-in for a real migration
    tool (Flask-Migrate/Alembic), appropriate while the schema is still
    this early-stage; swap to Alembic once the schema stabilizes.
    """
    inspector = inspect(db.engine)
    if "pharmacies" not in inspector.get_table_names():
        return  # fresh DB — create_all() already built it with every column

    existing_columns = {col["name"] for col in inspector.get_columns("pharmacies")}
    with db.engine.begin() as conn:
        if "osm_id" not in existing_columns:
            conn.execute(text("ALTER TABLE pharmacies ADD COLUMN osm_id VARCHAR(64)"))
        if "source" not in existing_columns:
            conn.execute(text("ALTER TABLE pharmacies ADD COLUMN source VARCHAR(20) DEFAULT 'manual'"))


def sync_osm_pharmacy(osm_data):
    """Find or create the local Pharmacy row for a live OSM pharmacy.

    This is the bridge to the future medicines database: the first time a
    given OSM pharmacy is seen, a local row is created for it (empty medicine
    list). From then on it's addressable by its local `id` — e.g. for a
    pharmacist to log in and attach medicines/stock to that exact real,
    map-verified pharmacy.
    """
    pharmacy = Pharmacy.query.filter_by(osm_id=osm_data["osm_id"]).first()
    if pharmacy:
        return pharmacy

    pharmacy = Pharmacy(
        osm_id=osm_data["osm_id"],
        source="osm",
        name_en=osm_data["name"],
        name_ar=osm_data["name"],
        address_en=osm_data["address"] or "",
        address_ar=osm_data["address"] or "",
        latitude=osm_data["latitude"],
        longitude=osm_data["longitude"],
        status="open",  # OSM doesn't reliably expose live open/closed state
        phone=osm_data["phone"] or "",
        hours=osm_data["opening_hours"] or "",
    )
    db.session.add(pharmacy)
    db.session.commit()
    return pharmacy


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------
def register_page_routes(app):
    @app.route("/")
    def index():
        return render_template("index.html")


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
def register_api_routes(app):

    @app.route("/api/pharmacies")
    def list_pharmacies():
        pharmacies = Pharmacy.query.all()
        return jsonify({"count": len(pharmacies), "results": [p.to_dict() for p in pharmacies]})

    @app.route("/api/pharmacies/nearest")
    def nearest_pharmacies():
        """
        Query params:
          lat, lng        — REQUIRED. User's coordinates (from the browser
                             Geolocation API). Used both to query OpenStreetMap
                             for real nearby pharmacies and to compute distance.
          radius_m         — search radius in meters (default 5000 = 5km).
          q                — medicine name search (matches English or Arabic name).
          open_only        — "true" to only return currently-open pharmacies.
          in_stock_only    — "true" to only return pharmacies with at least one
                              in-stock medicine (relative to the `q` match, if any).

        Flow:
          1. Query the Overpass API (OpenStreetMap) for real amenity=pharmacy
             elements within `radius_m` of (lat, lng).
          2. Mirror each result into the local `pharmacies` table (keyed by
             osm_id) — this is the hook for attaching medicines/stock later.
          3. Compute exact distance with geopy's geodesic formula.
          4. Sort nearest-first and return as JSON.

        If Overpass is unreachable or rate-limited, falls back to whatever
        pharmacies already exist locally (from earlier successful syncs, or
        manually-added ones) within the same radius, so the endpoint degrades
        gracefully instead of returning nothing.
        """
        lat = request.args.get("lat", type=float)
        lng = request.args.get("lng", type=float)
        if lat is None or lng is None:
            return jsonify({"error": "lat and lng query parameters are required"}), 400

        radius_m = request.args.get("radius_m", default=5000, type=int)
        query = (request.args.get("q") or "").strip().lower()
        open_only = request.args.get("open_only", "false").lower() == "true"
        in_stock_only = request.args.get("in_stock_only", "false").lower() == "true"

        user_point = (lat, lng)
        osm_pharmacies = fetch_nearby_pharmacies(lat, lng, radius_m=radius_m)

        if osm_pharmacies:
            candidate_pharmacies = [sync_osm_pharmacy(p) for p in osm_pharmacies]
        else:
            # Overpass unreachable/rate-limited/no results — fall back to
            # local pharmacies (previously synced, or manually added) within range.
            radius_km = radius_m / 1000
            candidate_pharmacies = [
                p for p in Pharmacy.query.all()
                if geodesic(user_point, (p.latitude, p.longitude)).km <= radius_km
            ]

        results = []
        for pharmacy in candidate_pharmacies:
            medicines = pharmacy.medicines

            if query:
                medicines = [
                    m for m in medicines
                    if query in m.name_en.lower() or query in (m.name_ar or "")
                ]
                if not medicines:
                    continue

            if open_only and pharmacy.status != "open":
                continue

            if in_stock_only and not any(m.availability == "in_stock" for m in medicines):
                continue

            distance_km = geodesic(user_point, (pharmacy.latitude, pharmacy.longitude)).km
            results.append(pharmacy.to_dict(distance_km=distance_km, medicines=medicines))

        results.sort(key=lambda r: (r["distance_km"] is None, r["distance_km"]))

        return jsonify({
            "count": len(results),
            "results": results,
            "source": "openstreetmap" if osm_pharmacies else "local_fallback",
        })

    @app.route("/api/pharmacies/<int:pharmacy_id>")
    def get_pharmacy(pharmacy_id):
        pharmacy = Pharmacy.query.get_or_404(pharmacy_id)
        return jsonify(pharmacy.to_dict())

    @app.route("/api/pharmacies", methods=["POST"])
    def create_pharmacy():
        payload = request.get_json(force=True) or {}
        pharmacy = Pharmacy(
            name_en=payload.get("name_en", ""),
            name_ar=payload.get("name_ar", payload.get("name_en", "")),
            address_en=payload.get("address_en", ""),
            address_ar=payload.get("address_ar", payload.get("address_en", "")),
            latitude=payload.get("latitude", 0) or 0,
            longitude=payload.get("longitude", 0) or 0,
            status=payload.get("status", "open"),
            phone=payload.get("phone", ""),
            hours=payload.get("hours", ""),
        )
        db.session.add(pharmacy)
        db.session.commit()
        return jsonify(pharmacy.to_dict()), 201

    @app.route("/api/pharmacies/<int:pharmacy_id>", methods=["PUT"])
    def update_pharmacy(pharmacy_id):
        pharmacy = Pharmacy.query.get_or_404(pharmacy_id)
        payload = request.get_json(force=True) or {}
        for field in ("name_en", "name_ar", "address_en", "address_ar",
                      "latitude", "longitude", "status", "phone", "hours"):
            if field in payload:
                setattr(pharmacy, field, payload[field])
        db.session.commit()
        return jsonify(pharmacy.to_dict())

    @app.route("/api/pharmacies/<int:pharmacy_id>/medicines", methods=["POST"])
    def add_medicine(pharmacy_id):
        Pharmacy.query.get_or_404(pharmacy_id)  # 404 if the pharmacy doesn't exist
        payload = request.get_json(force=True) or {}
        medicine = Medicine(
            pharmacy_id=pharmacy_id,
            name_en=payload.get("name_en", ""),
            name_ar=payload.get("name_ar", payload.get("name_en", "")),
            form_en=payload.get("form_en", ""),
            form_ar=payload.get("form_ar", payload.get("form_en", "")),
            price=payload.get("price", 0) or 0,
            availability=payload.get("availability", "in_stock"),
        )
        db.session.add(medicine)
        db.session.commit()
        return jsonify(medicine.to_dict()), 201

    @app.route("/api/medicines/<int:medicine_id>", methods=["PUT"])
    def update_medicine(medicine_id):
        medicine = Medicine.query.get_or_404(medicine_id)
        payload = request.get_json(force=True) or {}
        for field in ("name_en", "name_ar", "form_en", "form_ar", "price", "availability"):
            if field in payload:
                setattr(medicine, field, payload[field])
        db.session.commit()
        return jsonify(medicine.to_dict())

    @app.route("/api/medicines/<int:medicine_id>", methods=["DELETE"])
    def delete_medicine(medicine_id):
        medicine = Medicine.query.get_or_404(medicine_id)
        db.session.delete(medicine)
        db.session.commit()
        return jsonify({"deleted": True, "id": medicine_id})


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------
def register_cli(app):
    @app.cli.command("seed-db")
    def seed_db_command():
        """Seed the database with mock pharmacy & medicine data (flask --app app seed-db)."""
        with app.app_context():
            created = seed_database(force=True)
            print("Seeded database with mock data." if created else "Seeding skipped.")


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
