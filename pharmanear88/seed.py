"""
Mock data for local development and testing.

Coordinates are real Khartoum-area locations spread a few kilometers apart
so the "nearest first" sorting and distance calculation are meaningful when
tested from a point anywhere in central Khartoum.
"""

from extensions import db
from models import Pharmacy, Medicine

PHARMACY_SEED = [
    {
        "name_en": "Tas'heel Pharmacy", "name_ar": "صيدلية تساهيل",
        "address_en": "Al-Riyadh, Khartoum", "address_ar": "الرياض، الخرطوم",
        "latitude": 15.583, "longitude": 32.538, "status": "open",
        "phone": "+249911000001", "hours": "8:00 AM – 11:00 PM",
        "medicines": [
            {"name_en": "Panadol Extra", "name_ar": "بنادول إكسترا",
             "form_en": "24 tablets", "form_ar": "24 قرص",
             "price": 3500, "availability": "in_stock"},
            {"name_en": "Amoxicillin 500mg", "name_ar": "أموكسيسيلين 500",
             "form_en": "Capsules", "form_ar": "كبسولات",
             "price": 5100, "availability": "low_stock"},
            {"name_en": "Vitamin C 1000mg", "name_ar": "فيتامين سي 1000",
             "form_en": "Effervescent tablets", "form_ar": "أقراص فوارة",
             "price": 2200, "availability": "in_stock"},
        ],
    },
    {
        "name_en": "Al-Mahmada Pharmacy", "name_ar": "صيدلية المحمدة",
        "address_en": "Al-Mahmada, Omdurman", "address_ar": "المحمدة، أم درمان",
        "latitude": 15.646, "longitude": 32.478, "status": "open",
        "phone": "+249911000002", "hours": "9:00 AM – 12:00 AM",
        "medicines": [
            {"name_en": "Metformin 500mg", "name_ar": "ميتفورمين 500",
             "form_en": "Tablets", "form_ar": "أقراص",
             "price": 2800, "availability": "in_stock"},
            {"name_en": "Ventolin Inhaler", "name_ar": "فينتولين بخاخ",
             "form_en": "Inhaler 100mcg", "form_ar": "بخاخ 100 مكغ",
             "price": 6700, "availability": "in_stock"},
            {"name_en": "Insulin Glargine", "name_ar": "إنسولين غلارجين",
             "form_en": "Injection pen", "form_ar": "قلم حقن",
             "price": 18000, "availability": "out_of_stock"},
        ],
    },
    {
        "name_en": "Ahl Al-Quran Pharmacy", "name_ar": "صيدلية أهل القرآن",
        "address_en": "Bahri, Khartoum North", "address_ar": "بحري، الخرطوم بحري",
        "latitude": 15.644, "longitude": 32.533, "status": "closed",
        "phone": "+249911000003", "hours": "8:00 AM – 10:00 PM",
        "medicines": [
            {"name_en": "Panadol Extra", "name_ar": "بنادول إكسترا",
             "form_en": "24 tablets", "form_ar": "24 قرص",
             "price": 3400, "availability": "in_stock"},
            {"name_en": "Augmentin 625mg", "name_ar": "أوجمنتين 625",
             "form_en": "Tablets", "form_ar": "أقراص",
             "price": 7200, "availability": "low_stock"},
        ],
    },
    {
        "name_en": "Al-Dawa Al-Shafi Pharmacy", "name_ar": "صيدلية الدواء الشافي",
        "address_en": "Al-Amarat, Khartoum", "address_ar": "العمارات، الخرطوم",
        "latitude": 15.574, "longitude": 32.547, "status": "open",
        "phone": "+249911000004", "hours": "24 hours",
        "medicines": [
            {"name_en": "Amoxicillin 500mg", "name_ar": "أموكسيسيلين 500",
             "form_en": "Capsules", "form_ar": "كبسولات",
             "price": 4900, "availability": "in_stock"},
            {"name_en": "Paracetamol Syrup", "name_ar": "شراب باراسيتامول",
             "form_en": "120ml bottle", "form_ar": "زجاجة 120مل",
             "price": 2100, "availability": "in_stock"},
            {"name_en": "Insulin Glargine", "name_ar": "إنسولين غلارجين",
             "form_en": "Injection pen", "form_ar": "قلم حقن",
             "price": 17500, "availability": "low_stock"},
        ],
    },
    {
        "name_en": "Kobri Soba Pharmacy", "name_ar": "صيدلية كبري سوبا",
        "address_en": "Soba, South Khartoum", "address_ar": "سوبا، جنوب الخرطوم",
        "latitude": 15.528, "longitude": 32.560, "status": "open",
        "phone": "+249911000005", "hours": "8:00 AM – 11:00 PM",
        "medicines": [
            {"name_en": "Ventolin Inhaler", "name_ar": "فينتولين بخاخ",
             "form_en": "Inhaler 100mcg", "form_ar": "بخاخ 100 مكغ",
             "price": 6900, "availability": "low_stock"},
            {"name_en": "Metformin 500mg", "name_ar": "ميتفورمين 500",
             "form_en": "Tablets", "form_ar": "أقراص",
             "price": 2700, "availability": "out_of_stock"},
            {"name_en": "Panadol Extra", "name_ar": "بنادول إكسترا",
             "form_en": "24 tablets", "form_ar": "24 قرص",
             "price": 3300, "availability": "in_stock"},
        ],
    },
]


def seed_database(force=False):
    """Populate the database with mock pharmacies + medicines.

    Returns True if seeding ran, False if the table already had data and
    `force` was not set (so this is safe to call on every app startup).
    """
    if Pharmacy.query.first() and not force:
        return False

    if force:
        Medicine.query.delete()
        Pharmacy.query.delete()

    for entry in PHARMACY_SEED:
        entry = dict(entry)
        medicines_data = entry.pop("medicines")
        pharmacy = Pharmacy(**entry)
        pharmacy.medicines = [Medicine(**m) for m in medicines_data]
        db.session.add(pharmacy)

    db.session.commit()
    return True
