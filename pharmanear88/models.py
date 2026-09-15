"""
Database schema for PharmaNear.

Two tables:
  - Pharmacy: a pharmacy location (name, coordinates, contact, status).
  - Medicine: a medicine listed by a pharmacy (name, price, availability),
    linked back to its pharmacy via a foreign key.

Written against Flask-SQLAlchemy so the same models work unchanged against
SQLite locally and Postgres/Supabase in production — only the
SQLALCHEMY_DATABASE_URI in app.py needs to change.
"""

from extensions import db


class Pharmacy(db.Model):
    __tablename__ = "pharmacies"

    id = db.Column(db.Integer, primary_key=True)

    # Links this local record back to the live OpenStreetMap element it was
    # discovered from (e.g. "node/123456"). This is the bridge that lets a
    # pharmacist claim a real, map-verified pharmacy and attach medicines to
    # it later — OSM stays the source of truth for "does this pharmacy exist
    # and where", while this local row owns the medicines/stock data.
    osm_id = db.Column(db.String(64), index=True, nullable=True)
    source = db.Column(db.String(20), nullable=False, default="manual")  # "manual" | "osm"

    name_en = db.Column(db.String(150), nullable=False)
    name_ar = db.Column(db.String(150), nullable=False)
    address_en = db.Column(db.String(255))
    address_ar = db.Column(db.String(255))
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(10), nullable=False, default="open")  # "open" | "closed"
    phone = db.Column(db.String(30))
    hours = db.Column(db.String(60))

    medicines = db.relationship(
        "Medicine",
        backref="pharmacy",
        cascade="all, delete-orphan",
        lazy=True,
    )

    def to_dict(self, distance_km=None, medicines=None):
        """Serialize to the JSON shape the frontend expects.

        `medicines` can be passed in explicitly (e.g. a filtered subset from
        a search) — otherwise all of this pharmacy's medicines are included.
        """
        med_list = self.medicines if medicines is None else medicines
        return {
            "id": self.id,
            "osm_id": self.osm_id,
            "source": self.source,
            "name": {"en": self.name_en, "ar": self.name_ar},
            "address": {"en": self.address_en, "ar": self.address_ar},
            "latitude": self.latitude,
            "longitude": self.longitude,
            "status": self.status,
            "is_open": self.status == "open",
            "phone": self.phone,
            "hours": self.hours,
            "distance_km": round(distance_km, 2) if distance_km is not None else None,
            "medicines": [m.to_dict() for m in med_list],
        }


class Medicine(db.Model):
    __tablename__ = "medicines"

    id = db.Column(db.Integer, primary_key=True)
    pharmacy_id = db.Column(db.Integer, db.ForeignKey("pharmacies.id"), nullable=False)
    name_en = db.Column(db.String(150), nullable=False)
    name_ar = db.Column(db.String(150), nullable=False)
    form_en = db.Column(db.String(150))
    form_ar = db.Column(db.String(150))
    price = db.Column(db.Float, default=0)
    # "in_stock" | "low_stock" | "out_of_stock"
    availability = db.Column(db.String(20), nullable=False, default="in_stock")

    def to_dict(self):
        return {
            "id": self.id,
            "pharmacy_id": self.pharmacy_id,
            "name": {"en": self.name_en, "ar": self.name_ar},
            "form": {"en": self.form_en, "ar": self.form_ar},
            "price": self.price,
            "availability": self.availability,
        }
