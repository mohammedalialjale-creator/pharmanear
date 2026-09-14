# PharmaNear — Flask backend

A modular Flask + SQLAlchemy rebuild of the PharmaNear pharmacy locator.

## Structure

```
pharmanear/
├── app.py            # app factory, page route, API endpoints, CLI seed command
├── models.py         # SQLAlchemy models: Pharmacy, Medicine
├── extensions.py      # shared `db` instance (avoids circular imports)
├── utils.py           # Haversine distance calculation
├── seed.py            # mock data + seeding logic
├── requirements.txt
├── vercel.json
├── templates/
│   └── index.html     # Jinja template (dark UI, customer + pharmacist views)
└── static/
    ├── css/style.css
    └── js/app.js       # geolocation capture, fetch() calls to the API, rendering
```

## Local setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

flask --app app seed-db         # optional — the app also seeds automatically on first run
flask --app app run --debug
```

Then open http://127.0.0.1:5000.

## Database

Uses SQLite by default (`pharmanear.db`, created automatically). To point at
Postgres/Supabase instead, set an environment variable before running:

```bash
export DATABASE_URL="postgresql://user:password@host:5432/dbname"
```

No code changes needed — `models.py` is plain SQLAlchemy and works against
either engine. `psycopg2-binary` is required if you switch to Postgres/Supabase:

```bash
pip install psycopg2-binary
```

## API endpoints

| Method | Path                                   | Description                                   |
|--------|-----------------------------------------|------------------------------------------------|
| GET    | `/api/pharmacies`                       | List all pharmacies                            |
| GET    | `/api/pharmacies/nearest?lat=&lng=&q=`  | Search + sort by distance (Haversine)          |
| GET    | `/api/pharmacies/<id>`                  | Get a single pharmacy                          |
| POST   | `/api/pharmacies`                       | Create a pharmacy                              |
| PUT    | `/api/pharmacies/<id>`                  | Update a pharmacy                              |
| POST   | `/api/pharmacies/<id>/medicines`        | Add a medicine to a pharmacy                   |
| PUT    | `/api/medicines/<id>`                   | Update a medicine                              |
| DELETE | `/api/medicines/<id>`                   | Delete a medicine                              |

`/api/pharmacies/nearest` query params:
- `lat`, `lng` — user coordinates (from the browser's Geolocation API); when present, results are sorted nearest-first.
- `q` — medicine name search (English or Arabic).
- `open_only=true` — only currently-open pharmacies.
- `in_stock_only=true` — only pharmacies with at least one in-stock medicine.

## Deploying to Vercel

```bash
vercel
```

`vercel.json` routes all requests to `app.py` (Vercel auto-detects the Flask
`app` object) and serves `/static/*` directly.

**Important:** Vercel's filesystem is read-only except `/tmp`, and `/tmp` is
wiped between cold starts. SQLite will "work" there but won't persist data
reliably. For a real deployment, set `DATABASE_URL` in the Vercel project's
environment variables to your Supabase/Postgres connection string — the code
already reads that variable automatically.

## Seeding

Seeding happens automatically on first run if the `pharmacies` table is
empty. To force re-seed (wipes and reloads the 5 mock pharmacies):

```bash
flask --app app seed-db
```
