"""
GoHighLevel (GHL) integration for DumpDynasty Marketing Agent.
Handles creating/updating contacts in GHL CRM.
"""

import requests
from config import GHL_API_KEY, GHL_BASE_URL, GHL_LOCATION_ID


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {GHL_API_KEY}",
        "Content-Type": "application/json",
        "Version": "2021-07-28",
    }


def search_contact_by_phone(phone: str) -> dict | None:
    """Look up an existing GHL contact by phone number."""
    if not phone:
        return None
    params = {"phone": phone}
    if GHL_LOCATION_ID:
        params["locationId"] = GHL_LOCATION_ID
    resp = requests.get(f"{GHL_BASE_URL}/contacts/lookup", headers=_headers(), params=params)
    if resp.status_code == 200:
        data = resp.json()
        contacts = data.get("contacts") or []
        return contacts[0] if contacts else None
    return None


def search_contact_by_email(email: str) -> dict | None:
    """Look up an existing GHL contact by email address."""
    if not email:
        return None
    params = {"email": email}
    if GHL_LOCATION_ID:
        params["locationId"] = GHL_LOCATION_ID
    resp = requests.get(f"{GHL_BASE_URL}/contacts/lookup", headers=_headers(), params=params)
    if resp.status_code == 200:
        data = resp.json()
        contacts = data.get("contacts") or []
        return contacts[0] if contacts else None
    return None


def create_contact(lead: dict) -> dict:
    """
    Create a new contact in GoHighLevel from a lead dict.

    Expected lead keys: name, phone, email, address, city, state,
                        zip_code, website, category, source
    Returns the GHL API response dict.
    """
    first_name, last_name = _split_name(lead.get("name", ""))

    payload = {
        "firstName": first_name,
        "lastName": last_name,
        "phone": lead.get("phone", ""),
        "email": lead.get("email", ""),
        "address1": lead.get("address", ""),
        "city": lead.get("city", ""),
        "state": lead.get("state", ""),
        "postalCode": lead.get("zip_code", ""),
        "website": lead.get("website", ""),
        "source": lead.get("source", "Apify Scraper"),
        "tags": _build_tags(lead),
        "customField": _build_custom_fields(lead),
    }

    if GHL_LOCATION_ID:
        payload["locationId"] = GHL_LOCATION_ID

    # Remove empty strings so GHL doesn't reject the payload
    payload = {k: v for k, v in payload.items() if v not in ("", None, [])}

    resp = requests.post(f"{GHL_BASE_URL}/contacts/", headers=_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()


def update_contact(contact_id: str, lead: dict) -> dict:
    """Update an existing GHL contact with fresh lead data."""
    payload = {
        "website": lead.get("website", ""),
        "address1": lead.get("address", ""),
        "city": lead.get("city", ""),
        "state": lead.get("state", ""),
        "postalCode": lead.get("zip_code", ""),
        "tags": _build_tags(lead),
    }
    payload = {k: v for k, v in payload.items() if v not in ("", None, [])}

    resp = requests.put(f"{GHL_BASE_URL}/contacts/{contact_id}", headers=_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()


def upsert_contact(lead: dict) -> tuple[dict, bool]:
    """
    Create or update a GHL contact for the given lead.

    Returns:
        (contact_data, created) where created=True if a new contact was made.
    """
    existing = None
    if lead.get("phone"):
        existing = search_contact_by_phone(lead["phone"])
    if not existing and lead.get("email"):
        existing = search_contact_by_email(lead["email"])

    if existing:
        contact_id = existing.get("id") or existing.get("contact", {}).get("id")
        if contact_id:
            updated = update_contact(contact_id, lead)
            return updated, False

    created = create_contact(lead)
    return created, True


def add_contact_to_campaign(contact_id: str, campaign_id: str) -> dict:
    """Add an existing contact to a GHL campaign."""
    resp = requests.post(
        f"{GHL_BASE_URL}/contacts/{contact_id}/campaigns/{campaign_id}",
        headers=_headers(),
    )
    resp.raise_for_status()
    return resp.json()


def get_pipelines() -> list[dict]:
    """Return all pipelines for the configured location."""
    params = {}
    if GHL_LOCATION_ID:
        params["locationId"] = GHL_LOCATION_ID
    resp = requests.get(f"{GHL_BASE_URL}/pipelines/", headers=_headers(), params=params)
    if resp.status_code == 200:
        return resp.json().get("pipelines", [])
    return []


def create_opportunity(contact_id: str, pipeline_id: str, stage_id: str, name: str, monetary_value: float = 0) -> dict:
    """Create a sales opportunity in a GHL pipeline for a contact."""
    payload = {
        "pipelineId": pipeline_id,
        "stageId": stage_id,
        "contactId": contact_id,
        "name": name,
        "monetaryValue": monetary_value,
        "status": "open",
    }
    if GHL_LOCATION_ID:
        payload["locationId"] = GHL_LOCATION_ID

    resp = requests.post(f"{GHL_BASE_URL}/opportunities/", headers=_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split(" ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return full_name, ""


def _build_tags(lead: dict) -> list[str]:
    tags = ["dump-dynasty-lead", "apify-scraped"]
    category = lead.get("category", "")
    if category:
        tag = category.lower().replace(" ", "-")[:50]
        tags.append(tag)
    return tags


def _build_custom_fields(lead: dict) -> list[dict]:
    fields = []
    if lead.get("rating"):
        fields.append({"key": "google_rating", "field_value": str(lead["rating"])})
    if lead.get("review_count"):
        fields.append({"key": "google_review_count", "field_value": str(lead["review_count"])})
    if lead.get("category"):
        fields.append({"key": "business_category", "field_value": lead["category"]})
    return fields
