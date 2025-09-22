# scraper.py
import os
import requests
import math
from fpdf import FPDF
from time import sleep

# --- configurable via env / secrets ---
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST")  # e.g. realty-in-au.p.rapidapi.com
RAPIDAPI_PATH = os.getenv("RAPIDAPI_PATH", "/properties/list-for-sale")  # change if your endpoint is different
SUBURB = os.getenv("SEARCH_SUBURB", "Parramatta")
STATE = os.getenv("SEARCH_STATE", "NSW")
MAX_PRICE = int(os.getenv("SEARCH_MAX_PRICE", "500000"))
MIN_BEDS = int(os.getenv("SEARCH_MIN_BEDS", "1"))
MAX_BEDS = int(os.getenv("SEARCH_MAX_BEDS", "2"))
MIN_CARSPACES = int(os.getenv("SEARCH_MIN_CARSPACES", "1"))
LIMIT = int(os.getenv("SEARCH_LIMIT", "40"))

# Parramatta station / park coordinates (for distance)
STATION_COORDS = (-33.8178, 151.0035)
PARK_COORDS = (-33.8145, 151.0024)

# ---- helpers ----
def km_to_walk_minutes(km):
    # ~5 km/h walking speed => 12 min per km
    return int(round(km * 12))

def haversine_km(lat1, lon1, lat2, lon2):
    # simple haversine distance (km)
    R = 6371.0
    import math
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def debug_print(s):
    print(s)

def find_listings_container(j):
    # Look for common field names that hold a list of listings
    candidates = ["properties", "listings", "results", "data", "items"]
    if isinstance(j, dict):
        for k in candidates:
            if k in j and isinstance(j[k], list):
                return j[k]
        # fallback: find first list of dicts
        for k,v in j.items():
            if isinstance(v, list) and len(v) and isinstance(v[0], dict):
                return v
    if isinstance(j, list):
        return j
    return None

def try_get(o, keys):
    for k in keys:
        if isinstance(o, dict) and k in o:
            return o[k]
    return None

def extract_field(listing):
    # try multiple common key names
    price = try_get(listing, ["price", "price_display", "price_value", "price_min", "asking_price"])
    beds = try_get(listing, ["bedrooms", "beds", "bed"])
    baths = try_get(listing, ["bathrooms", "baths", "bath"])
    cars = try_get(listing, ["carspaces", "cars", "parking", "car"])
    address = try_get(listing, ["address", "full_address", "displayable_address", "formatted_address"])
    url = try_get(listing, ["url", "ldp_url", "listing_url", "detail_url"])
    lat = try_get(listing, ["lat", "latitude"])
    lon = try_get(listing, ["lon", "lng", "longitude"])
    # simple sanitise
    try:
        price_val = None
        if isinstance(price, (int, float)):
            price_val = int(price)
        elif isinstance(price, str):
            import re
            nums = re.findall(r"\d+", price.replace(",", ""))
            if nums:
                price_val = int("".join(nums))
    except Exception:
        price_val = None

    try:
        beds = int(beds) if beds not in (None, "") else None
    except Exception:
        beds = None
    try:
        baths = int(baths) if baths not in (None, "") else None
    except Exception:
        baths = None
    try:
        cars = int(cars) if cars not in (None, "") else None
    except Exception:
        cars = None

    return {
        "price_raw": price,
        "price": price_val,
        "beds": beds,
        "baths": baths,
        "cars": cars,
        "address": address,
        "url": url,
        "lat": lat,
        "lon": lon
    }

# ---- main ----
def run_search_and_build_pdf():
    if not RAPIDAPI_KEY or not RAPIDAPI_HOST:
        raise SystemExit("RAPIDAPI_KEY and RAPIDAPI_HOST must be set as environment variables.")

    url = f"https://{RAPIDAPI_HOST}{RAPIDAPI_PATH}"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }

    # Example params: the exact names vary by API — test in RapidAPI UI and adjust accordingly
    params = {
        "suburb": SUBURB,
        "state": STATE,
        "price_max": MAX_PRICE,
        "bedrooms_min": MIN_BEDS,
        "bedrooms_max": MAX_BEDS,
        "carspaces_min": MIN_CARSPACES,
        "limit": LIMIT,
        "offset": 0
    }

    debug_print(f"Requesting {url} with params {params} ...")
    r = requests.get(url, headers=headers, params=params, timeout=30)
    debug_print(f"Status: {r.status_code}")
    if r.status_code != 200:
        debug_print("Response text (truncated):")
        debug_print(r.text[:1000])
        raise SystemExit("API request failed. Check host/key/params in RapidAPI UI.")

    j = r.json()
    listings = find_listings_container(j)
    if not listings:
        debug_print("Couldn't find listings in response. Dumping JSON keys for troubleshooting:")
        debug_print(list(j.keys()) if isinstance(j, dict) else str(type(j)))
        raise SystemExit("No listings container found. Please paste a small sample JSON and I will adapt the script.")

    props = []
    for L in listings:
        item = extract_field(L)
        # geocode if lat/lon missing *attempt* (rate limit friendly: sleep)
        if item["lat"] is None or item["lon"] is None:
            if item["address"]:
                # use Nominatim open API (be kind — rate limit)
                try:
                    q = f"{item['address']}, Parramatta NSW"
                    geocode_url = "https://nominatim.openstreetmap.org/search"
                    rgeo = requests.get(geocode_url, params={"q": q, "format":"json","limit":1}, headers={"User-Agent":"parramatta-bot/1.0"}, timeout=10)
                    geodata = rgeo.json()
                    if geodata:
                        item["lat"] = float(geodata[0]["lat"])
                        item["lon"] = float(geodata[0]["lon"])
                        sleep(1)  # be gentle
                except Exception:
                    pass

        # distance calc if lat/lon exists
        dist_station_km = None
        dist_park_km = None
        if item["lat"] and item["lon"]:
            try:
                dist_station_km = round(haversine_km(float(item["lat"]), float(item["lon"]), STATION_COORDS[0], STATION_COORDS[1]), 2)
                dist_park_km = round(haversine_km(float(item["lat"]), float(item["lon"]), PARK_COORDS[0], PARK_COORDS[1]), 2)
            except Exception:
                pass

        # pros/cons simple logic
        pros = []
        cons = []
        if item["cars"] and item["cars"] >= 1:
            pros.append("Has 1+ car space")
        else:
            cons.append("No dedicated parking listed")

        if item["beds"] == 2 and item["baths"] and item["baths"] >= 2:
            pros.append("2 beds + 2 baths")
        elif item["beds"] == 2 and (not item["baths"] or item["baths"] == 1):
            cons.append("Only 1 bath for 2 beds")

        if item["price"] and item["price"] <= (MAX_PRICE - 50000):
            pros.append("Good value under budget")
        elif item["price"] and item["price"] >= (MAX_PRICE - 10000):
            cons.append("Close to top of budget")

        props.append({
            "raw": item,
            "dist_station_km": dist_station_km,
            "dist_park_km": dist_park_km,
            "pros": pros,
            "cons": cons
        })

    # --- Make PDF ---
    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 8, "Parramatta Property Listings (Under ${})".format(MAX_PRICE), ln=True, align="C")
    pdf.ln(6)

    for p in props:
        i = p["raw"]
        title = i.get("address") or str(i.get("url") or "Property")
        price_text = i.get("price_raw") or (f"${i.get('price')}" if i.get("price") else "Price unknown")
        pdf.set_font("Arial", "B", 11)
        pdf.multi_cell(0, 7, f"{title} — {price_text}")
        pdf.set_font("Arial", size=10)
        beds = i.get("beds") or "?"
        baths = i.get("baths") or "?"
        cars = i.get("cars") or "?"
        pdf.multi_cell(0, 6, f"{beds} bed | {baths} bath | {cars} car")
        if i.get("url"):
            pdf.multi_cell(0, 6, f"Link: {i.get('url')}")
        if p["dist_station_km"] is not None:
            mins = km_to_walk_minutes(p["dist_station_km"])
            pdf.multi_cell(0, 6, f"Distance: {p['dist_station_km']} km to station (~{mins} min walk)")
        if p["dist_park_km"] is not None:
            mins2 = km_to_walk_minutes(p["dist_park_km"])
            pdf.multi_cell(0, 6, f"Distance: {p['dist_park_km']} km to Parramatta Park (~{mins2} min walk)")
        if p["pros"]:
            pdf.multi_cell(0, 6, "Pros: " + ", ".join(p["pros"]))
        if p["cons"]:
            pdf.multi_cell(0, 6, "Cons: " + ", ".join(p["cons"]))
        pdf.ln(3)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)

    outname = "listings.pdf"
    pdf.output(outname)
    print("PDF written:", outname)

if __name__ == "__main__":
    run_search_and_build_pdf()
