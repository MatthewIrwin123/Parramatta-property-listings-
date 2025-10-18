# scraper.py
# Uses RapidAPI "Realty in AU" (or similar) to fetch listings and create listings.pdf
import os
import requests
import time
from fpdf import FPDF
import math

# ---- Config from environment (set these as GitHub Secrets/ENV)
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST")  # e.g. realty-in-au.p.rapidapi.com
RAPIDAPI_PATH = os.getenv("RAPIDAPI_PATH", "/properties/v2/list-for-sale")  # change if endpoint differs
SUBURB = os.getenv("SEARCH_SUBURB", "Parramatta")
STATE = os.getenv("SEARCH_STATE", "NSW")
MAX_PRICE = int(os.getenv("SEARCH_MAX_PRICE", "500000"))
MIN_BEDS = int(os.getenv("SEARCH_MIN_BEDS", "1"))
MAX_BEDS = int(os.getenv("SEARCH_MAX_BEDS", "2"))
MIN_CARSPACES = int(os.getenv("SEARCH_MIN_CARSPACES", "1"))
LIMIT = int(os.getenv("SEARCH_LIMIT", "40"))

# Parramatta station / park coords (for simple distances)
STATION_COORDS = (-33.8178, 151.0035)
PARK_COORDS = (-33.8145, 151.0024)

# ---- Helpers ----
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def km_to_walk_minutes(km):
    # ~5 km/h -> 12 min per km
    return int(round(km * 12))

def debug_print(*args):
    print(*args)

def find_listings_container(j):
    candidates = ["properties", "listings", "results", "data", "items"]
    if isinstance(j, dict):
        for k in candidates:
            if k in j and isinstance(j[k], list):
                return j[k]
        # fallback: first list-of-dicts
        for k, v in j.items():
            if isinstance(v, list) and len(v) and isinstance(v[0], dict):
                return v
    if isinstance(j, list):
        return j
    return None

def try_get(obj, keys):
    for k in keys:
        if isinstance(obj, dict) and k in obj:
            return obj[k]
    return None

def extract_field(listing):
    price = try_get(listing, ["price", "price_display", "price_value", "price_min", "asking_price"])
    beds = try_get(listing, ["bedrooms", "beds", "bed"])
    baths = try_get(listing, ["bathrooms", "baths", "bath"])
    cars = try_get(listing, ["carspaces", "cars", "parking", "car"])
    address = try_get(listing, ["address", "full_address", "displayable_address", "formatted_address"])
    url = try_get(listing, ["url", "ldp_url", "listing_url", "detail_url"])
    lat = try_get(listing, ["lat", "latitude"])
    lon = try_get(listing, ["lon", "lng", "longitude"])

    # Normalize price
    price_val = None
    if isinstance(price, (int, float)):
        price_val = int(price)
    elif isinstance(price, str):
        import re
        nums = re.findall(r"\d+", price.replace(",", ""))
        if nums:
            price_val = int("".join(nums))

    # Normalize ints
    def to_int(v):
        try:
            return int(v)
        except Exception:
            return None

    return {
        "price_raw": price,
        "price": price_val,
        "beds": to_int(beds),
        "baths": to_int(baths),
        "cars": to_int(cars),
        "address": address,
        "url": url,
        "lat": lat,
        "lon": lon
    }

# ---- Main function ----
def run_search_and_build_pdf():
    if not RAPIDAPI_KEY or not RAPIDAPI_HOST:
        raise SystemExit("RAPIDAPI_KEY and RAPIDAPI_HOST must be set in environment / secrets.")

    url = f"https://{RAPIDAPI_HOST}{RAPIDAPI_PATH}"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }

    # NOTE: parameter names differ by provider. Adjust after testing in RapidAPI GUI.
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

    debug_print("Requesting:", url)
    debug_print("Params:", params)
    r = requests.get(url, headers=headers, params=params, timeout=30)
    debug_print("Status:", r.status_code)
    if r.status_code != 200:
        debug_print("Response text (first 800 chars):")
        debug_print(r.text[:800])
        raise SystemExit("API request failed. Check RAPIDAPI_KEY, RAPIDAPI_HOST, and params in RapidAPI UI.")

    j = r.json()
    listings = find_listings_container(j)
    if not listings:
        debug_print("Couldn't locate listing container. Top-level JSON keys:")
        if isinstance(j, dict):
            debug_print(list(j.keys()))
        else:
            debug_print(type(j))
        raise SystemExit("No listings container found. Paste sample JSON into chat and I'll adapt extractors.")

    results = []
    for L in listings:
        item = extract_field(L)

        # If no coords, attempt gentle Nominatim geocode (rate-limited)
        if (item["lat"] is None or item["lon"] is None) and item["address"]:
            try:
                geocode = requests.get("https://nominatim.openstreetmap.org/search",
                                       params={"q": f"{item['address']}, Parramatta NSW", "format": "json", "limit": 1},
                                       headers={"User-Agent": "parramatta-scraper/1.0"}, timeout=10)
                g = geocode.json()
                if g:
                    item["lat"] = float(g[0]["lat"])
                    item["lon"] = float(g[0]["lon"])
                    time.sleep(1)
            except Exception:
                pass

        dist_station_km = None
        dist_park_km = None
        if item.get("lat") and item.get("lon"):
            try:
                dist_station_km = round(haversine_km(float(item["lat"]), float(item["lon"]), STATION_COORDS[0], STATION_COORDS[1]), 2)
                dist_park_km = round(haversine_km(float(item["lat"]), float(item["lon"]), PARK_COORDS[0], PARK_COORDS[1]), 2)
            except Exception:
                pass

        # pros/cons rules
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
            pros.append("Good value below budget")
        elif item["price"] and item["price"] >= (MAX_PRICE - 10000):
            cons.append("Close to top of budget")

        results.append({
            "item": item,
            "dist_station_km": dist_station_km,
            "dist_park_km": dist_park_km,
            "pros": pros,
            "cons": cons
        })

    # --- Create PDF ---
    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 8, f"Parramatta Listings — Under ${MAX_PRICE}", ln=True, align="C")
    pdf.ln(6)
    pdf.set_font("Arial", size=11)

    if not results:
        pdf.multi_cell(0, 6, "No listings found for your filters.")
    for ritem in results:
        i = ritem["item"]
        title = i.get("address") or (i.get("url") or "Property")
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
        if ritem["dist_station_km"] is not None:
            mins = km_to_walk_minutes(ritem["dist_station_km"])
            pdf.multi_cell(0, 6, f"Distance: {ritem['dist_station_km']} km to Parramatta Station (~{mins} min walk)")
        if ritem["dist_park_km"] is not None:
            mins2 = km_to_walk_minutes(ritem["dist_park_km"])
            pdf.multi_cell(0, 6, f"Distance: {ritem['dist_park_km']} km to Parramatta Park (~{mins2} min walk)")
        if ritem["pros"]:
            pdf.multi_cell(0, 6, "Pros: " + ", ".join(ritem["pros"]))
        if ritem["cons"]:
            pdf.multi_cell(0, 6, "Cons: " + ", ".join(ritem["cons"]))
        pdf.ln(3)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)

    outname = "listings.pdf"
    pdf.output(outname)
    print("Wrote PDF:", outname)

if __name__ == "__main__":
    run_search_and_build_pdf()
