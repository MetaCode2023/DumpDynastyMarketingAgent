"""
Apify integration for DumpDynasty Marketing Agent.
Handles scraping leads via Apify actors (Google Maps, etc.).
"""

from apify_client import ApifyClient
from config import APIFY_API_TOKEN, GOOGLE_MAPS_ACTOR_ID


def get_client() -> ApifyClient:
    return ApifyClient(APIFY_API_TOKEN)


def scrape_google_maps_leads(
    search_terms: list[str],
    location: str,
    max_results: int = 50,
) -> list[dict]:
    """
    Run the Apify Google Maps Scraper to find local businesses as leads.

    Args:
        search_terms: Keywords to search (e.g. ["construction companies", "contractors"])
        location: City/region to target (e.g. "Houston, TX")
        max_results: Maximum number of results to return

    Returns:
        List of lead dicts with name, phone, email, address, website, etc.
    """
    client = get_client()

    run_input = {
        "searchStringsArray": [f"{term} {location}" for term in search_terms],
        "maxCrawledPlacesPerSearch": max_results,
        "language": "en",
        "exportPlaceUrls": False,
        "includeHistogram": False,
        "includeOpeningHours": False,
        "includePeopleAlsoSearch": False,
        "additionalInfo": False,
    }

    print(f"[Apify] Starting Google Maps scrape for: {search_terms} in {location}")
    run = client.actor(GOOGLE_MAPS_ACTOR_ID).call(run_input=run_input)

    leads = []
    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        print("[Apify] No dataset returned from actor run.")
        return leads

    for item in client.dataset(dataset_id).iterate_items():
        lead = _parse_google_maps_item(item)
        if lead:
            leads.append(lead)

    print(f"[Apify] Scraped {len(leads)} leads from Google Maps.")
    return leads


def _parse_google_maps_item(item: dict) -> dict | None:
    """Extract relevant fields from a Google Maps scraper result."""
    name = item.get("title") or item.get("name")
    if not name:
        return None

    phone = item.get("phone") or item.get("phoneUnformatted") or ""
    email = _extract_email(item)
    address = item.get("address") or item.get("street") or ""
    city = item.get("city") or ""
    state = item.get("state") or ""
    zip_code = item.get("postalCode") or item.get("zipCode") or ""
    website = item.get("website") or ""
    category = item.get("categoryName") or item.get("categories", [""])[0] if item.get("categories") else ""
    rating = item.get("totalScore") or item.get("rating") or 0
    review_count = item.get("reviewsCount") or item.get("reviewCount") or 0

    return {
        "name": name,
        "phone": phone,
        "email": email,
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "website": website,
        "category": category,
        "rating": rating,
        "review_count": review_count,
        "source": "Google Maps (Apify)",
    }


def _extract_email(item: dict) -> str:
    """Try to pull an email from various possible fields."""
    if item.get("email"):
        return item["email"]
    emails = item.get("emails") or []
    if emails:
        return emails[0] if isinstance(emails[0], str) else emails[0].get("value", "")
    return ""


def get_actor_run_status(run_id: str) -> dict:
    """Return the status of a previously started actor run."""
    client = get_client()
    return client.run(run_id).get()


def fetch_dataset_items(dataset_id: str) -> list[dict]:
    """Fetch all items from an Apify dataset by ID."""
    client = get_client()
    return list(client.dataset(dataset_id).iterate_items())
