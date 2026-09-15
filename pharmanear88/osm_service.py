"""
Live pharmacy lookup via the Overpass API (OpenStreetMap).

Given the user's coordinates, this queries OSM for real amenity=pharmacy
elements within a radius and normalizes them into a simple dict shape.
No API key needed — Overpass is a free public service — but requests are
kept modest (radius, timeout) to be a good citizen of the shared instance,
and every failure mode degrades to an empty list rather than raising, so a
slow/rate-limited Overpass server never takes the whole endpoint down.
"""

import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_RADIUS_M = 5000
REQUEST_TIMEOUT_S = 15


def fetch_nearby_pharmacies(lat, lng, radius_m=DEFAULT_RADIUS_M):
    """Query Overpass for amenity=pharmacy within radius_m of (lat, lng).

    Returns a list of dicts:
        { osm_id, name, latitude, longitude, address, phone, opening_hours }
    Returns [] on any network/parsing failure.
    """
    query = f"""
    [out:json][timeout:{REQUEST_TIMEOUT_S}];
    (
      node["amenity"="pharmacy"](around:{radius_m},{lat},{lng});
      way["amenity"="pharmacy"](around:{radius_m},{lat},{lng});
      relation["amenity"="pharmacy"](around:{radius_m},{lat},{lng});
    );
    out center tags;
    """

    try:
        response = requests.post(
            OVERPASS_URL, data={"data": query}, timeout=REQUEST_TIMEOUT_S
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return []

    pharmacies = []
    for element in payload.get("elements", []):
        point = _element_point(element)
        if point is None:
            continue

        tags = element.get("tags", {})
        name = tags.get("name") or tags.get("name:ar") or tags.get("brand") or "Pharmacy"

        pharmacies.append({
            "osm_id": f"{element.get('type')}/{element.get('id')}",
            "name": name,
            "latitude": point[0],
            "longitude": point[1],
            "address": _build_address(tags),
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "opening_hours": tags.get("opening_hours"),
        })

    return pharmacies


def _element_point(element):
    """Nodes have lat/lon directly; ways/relations expose a computed center
    (requires the Overpass query to include `out center`)."""
    if "lat" in element and "lon" in element:
        return element["lat"], element["lon"]
    center = element.get("center")
    if center:
        return center["lat"], center["lon"]
    return None


def _build_address(tags):
    parts = [p for p in (tags.get("addr:street"), tags.get("addr:city") or tags.get("addr:suburb")) if p]
    return ", ".join(parts) if parts else None
