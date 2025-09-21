import requests
from bs4 import BeautifulSoup
from fpdf import FPDF
from geopy.distance import geodesic

# Constants
STATION_COORDS = (-33.8178, 151.0035)  # Parramatta Station
PARK_COORDS = (-33.8145, 151.0024)     # Parramatta Park

# --- HELPER: calculate distance in km ---
def calc_distance(address):
    try:
        # Use OpenStreetMap Nominatim
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={address}, Parramatta, NSW"
        r = requests.get(url).json()
        if not r:
            return None, None
        lat, lon = float(r[0]['lat']), float(r[0]['lon'])
        prop_coords = (lat, lon)
        station_km = geodesic(prop_coords, STATION_COORDS).km
        park_km = geodesic(prop_coords, PARK_COORDS).km
        return round(station_km, 2), round(park_km, 2)
    except:
        return None, None

# --- HELPER: pros & cons based on property details ---
def analyze_property(beds, baths, cars, price):
    pros, cons = [], []
    if cars >= 1:
        pros.append("Has car space")
    else:
        cons.append("No parking")

    if beds == 2 and baths == 2:
        pros.append("2 bathrooms for 2 bedrooms (good balance)")
    elif beds == 2 and baths == 1:
        cons.append("Only 1 bathroom for 2 bedrooms")

    if price < 450000:
        pros.append("Affordable entry point for Parramatta")
    elif price >= 490000:
        cons.append("Near the top of your budget")

    return pros, cons

# --- MAIN scrape function (placeholder example for realestate.com.au) ---
def scrape_realestate():
    url = "https://www.realestate.com.au/buy/property-unit+apartment-with-1-2-bedrooms-under-500000-in-parramatta,+nsw+2150/list-1"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")
    listings = []

    for card in soup.select("article"):  # site-specific selectors may change
        title = card.get_text(" ", strip=True)
        link = card.find("a", href=True)
        if not link:
            continue
        # (Parsing price, beds, baths, cars would need exact selectors)
        # Example placeholder values:
        price, beds, baths, cars = 500000, 2, 1, 1
        address = "Parramatta NSW"

        pros, cons = analyze_property(beds, baths, cars, price)
        dist_station, dist_park = calc_distance(address)

        listings.append({
            "title": title,
            "price": price,
            "beds": beds,
            "baths": baths,
            "cars": cars,
            "address": address,
            "link": "https://www.realestate.com.au" + link['href'],
            "pros": pros,
            "cons": cons,
            "dist_station": dist_station,
            "dist_park": dist_park
        })
    return listings

# --- Generate PDF ---
def make_pdf(listings, filename="Parramatta_Listings.pdf"):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, "Parramatta Property Listings", ln=True, align="C")

    for prop in listings:
        pdf.ln(8)
        pdf.set_font("Arial", "B", 12)
        pdf.multi_cell(0, 8, f"{prop['title']} - ${prop['price']}")
        pdf.set_font("Arial", size=10)
        pdf.multi_cell(0, 6, f"{prop['beds']} bed, {prop['baths']} bath, {prop['cars']} car")
        pdf.multi_cell(0, 6, f"Address: {prop['address']}")
        if prop['dist_station']:
            pdf.multi_cell(0, 6, f"Distance: {prop['dist_station']} km to station, {prop['dist_park']} km to park")
        pdf.multi_cell(0, 6, "Pros: " + ", ".join(prop['pros']))
        pdf.multi_cell(0, 6, "Cons: " + ", ".join(prop['cons']))
        pdf.multi_cell(0, 6, f"Link: {prop['link']}")
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())

    pdf.output(filename)

if __name__ == "__main__":
    results = scrape_realestate()
    make_pdf(results)
    print("PDF created successfully!")
