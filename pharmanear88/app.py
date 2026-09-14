"""
PharmaNear — Flask backend.

Structure:
  app.py        — application factory, routes, API endpoints
  models.py     — SQLAlchemy models (Pharmacy, Medicine)
  extensions.py — shared `db` instance
  utils.py      — Haversine distance calculation
  seed.py       — mock data + seeding logic
  templates/    — Jinja templates (index.html)
  static/       — CSS + JS served to the browser

Local run:
    pip install -r requirements.txt
    flask --app app seed-db     # optional — also runs automatically on first boot
    flask --app app run --debug

Switching from SQLite to Supabase/Postgres later: just set the
DATABASE_URL environment variable to your Postgres connection string
(e.g. the one Supabase gives you) — nothing else in this file needs to
change, since the models are plain SQLAlchemy.
"""

import os

from flask import Flask, render_template, request, jsonify

from extensions import db
from models import Pharmacy, Medicine
from utils import haversine_km
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
        seed_database()  # no-op if the database already has data

    register_page_routes(app)
    register_api_routes(app)
    register_cli(app)

    return app


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
          lat, lng        — user's coordinates (from the browser Geolocation API).
                             Optional — if omitted, results are unsorted by distance.
          q                — medicine name search (matches English or Arabic name).
          open_only        — "true" to only return currently-open pharmacies.
          in_stock_only    — "true" to only return pharmacies with at least one
                              in-stock medicine (relative to the `q` match, if any).
        """
        lat = request.args.get("lat", type=float)
        lng = request.args.get("lng", type=float)
        query = (request.args.get("q") or "").strip().lower()
        open_only = request.args.get("open_only", "false").lower() == "true"
        in_stock_only = request.args.get("in_stock_only", "false").lower() == "true"

        pharmacies = Pharmacy.query.all()
        results = []

        for pharmacy in pharmacies:
            medicines = pharmacy.medicines

            if query:
                medicines = [
                    m for m in medicines
                    if query in m.name_en.lower() or query in (m.name_ar or "")
                ]
                if not medicines:
                    continue  # this pharmacy has no matching medicine

            if open_only and pharmacy.status != "open":
                continue

            if in_stock_only and not any(m.availability == "in_stock" for m in medicines):
                continue

            distance_km = haversine_km(lat, lng, pharmacy.latitude, pharmacy.longitude)
            results.append(pharmacy.to_dict(distance_km=distance_km, medicines=medicines))

        # Sort by distance (nearest first) whenever we have the user's location.
        if lat is not None and lng is not None:
            results.sort(key=lambda r: (r["distance_km"] is None, r["distance_km"]))

        return jsonify({"count": len(results), "results": results})

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
