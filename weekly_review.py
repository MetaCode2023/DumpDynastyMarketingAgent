#!/usr/bin/env python3
"""
Dump Dynasty — Weekly Contact Status Reviewer

Runs once a week. For every contact in GHL it:
  1. Pulls their notes and tasks
  2. Asks Claude to assess engagement level
  3. Replaces any existing status:* tag with the new one
  4. Adds a timestamped note summarising the AI's reasoning

Status tags used:
  status:hot      — very active, strong buying signals
  status:warm     — engaged but not urgent
  status:cold     — low recent activity, needs a nudge
  status:inactive — no meaningful activity in 30+ days
  status:closed   — deal won/lost, no further follow-up needed

Setup
-----
  export GHL_API_KEY="pit-7f43ddf3-cf39-4a94-aeb4-ad90c0689a0a"
  export GHL_LOCATION_ID="<your-location-id>"   # from GHL Settings → Integrations
  export ANTHROPIC_API_KEY="<your-anthropic-key>"
  pip install -r requirements.txt
  python weekly_review.py

Cron (run every Monday at 8 am):
  0 8 * * 1 cd /path/to/DumpDynastyMarketingAgent && python weekly_review.py >> weekly_review.log 2>&1
"""

import os
import json
import time
import sys
from datetime import datetime, timezone
from typing import Optional

import requests
import anthropic
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────

GHL_TOKEN       = os.environ.get("GHL_API_KEY", "pit-7f43ddf3-cf39-4a94-aeb4-ad90c0689a0a")
GHL_LOCATION_ID = os.environ.get("GHL_LOCATION_ID", "")
ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")

GHL_BASE  = "https://services.leadconnectorhq.com"
GHL_HDRS  = {
    "Authorization": f"Bearer {GHL_TOKEN}",
    "Version": "2021-07-28",
    "Content-Type": "application/json",
}

VALID_STATUSES = {"status:hot", "status:warm", "status:cold", "status:inactive", "status:closed"}
MAX_NOTES      = 20   # notes sent to Claude per contact
MAX_TASKS      = 10   # tasks sent to Claude per contact

# ── GHL helpers ───────────────────────────────────────────────────────────────

def _ghl_request(method: str, path: str, **kwargs) -> dict:
    """HTTP call to GHL with simple retry on 429."""
    url = f"{GHL_BASE}{path}"
    for attempt in range(5):
        resp = requests.request(method, url, headers=GHL_HDRS, **kwargs)
        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"    Rate-limited, waiting {wait}s …")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()


def get_all_contacts() -> list[dict]:
    """Page through all contacts in the location."""
    contacts, cursor, cursor_id = [], None, None

    if not GHL_LOCATION_ID:
        print("ERROR: GHL_LOCATION_ID is not set. "
              "Find it in GHL → Settings → Integrations → API Keys.", file=sys.stderr)
        sys.exit(1)

    while True:
        params: dict = {"locationId": GHL_LOCATION_ID, "limit": 100}
        if cursor:
            params["startAfter"]   = cursor
            params["startAfterId"] = cursor_id

        data = _ghl_request("GET", "/contacts/", params=params)
        batch = data.get("contacts", [])
        if not batch:
            break
        contacts.extend(batch)

        # GHL pagination — next page cursors come from the last contact
        meta = data.get("meta", {})
        if meta.get("nextPageUrl") or len(batch) == 100:
            last = batch[-1]
            cursor    = last.get("dateAdded")
            cursor_id = last.get("id")
        else:
            break

    return contacts


def get_notes(contact_id: str) -> list[dict]:
    try:
        data = _ghl_request("GET", f"/contacts/{contact_id}/notes")
        return data.get("notes", [])
    except Exception as exc:
        print(f"    Couldn't fetch notes: {exc}")
        return []


def get_tasks(contact_id: str) -> list[dict]:
    try:
        data = _ghl_request("GET", f"/contacts/{contact_id}/tasks")
        return data.get("tasks", [])
    except Exception as exc:
        print(f"    Couldn't fetch tasks: {exc}")
        return []


def update_contact_tags(contact_id: str, old_tags: list[str], new_status: str) -> None:
    """Replace any existing status:* tag with new_status."""
    cleaned = [t for t in old_tags if t not in VALID_STATUSES]
    cleaned.append(new_status)
    _ghl_request("PUT", f"/contacts/{contact_id}", json={"tags": cleaned})


def add_note(contact_id: str, body: str) -> None:
    _ghl_request("POST", f"/contacts/{contact_id}/notes", json={"body": body})


# ── Claude analysis ───────────────────────────────────────────────────────────

class ContactAssessment(BaseModel):
    status: str           # one of the five valid statuses
    reasoning: str        # 2-4 sentences explaining why
    recommended_action: str  # what the sales team should do next


SYSTEM_PROMPT = """You are a CRM analyst for Dump Dynasty, a marketing agency.
Your job is to review a contact's activity history and assign an engagement status.

Use exactly one of these statuses:
  status:hot      — Highly engaged recently; strong interest or buying signals in the last 1-2 weeks
  status:warm     — Some engagement or positive signals but not urgent; follow up within 2-4 weeks
  status:cold     — Minimal interaction; last meaningful contact was weeks or months ago
  status:inactive — No meaningful activity for 30+ days; may need re-engagement campaign
  status:closed   — Deal clearly won or lost; no further active follow-up needed

Be direct and concise. Base your assessment entirely on the notes, tasks, and timestamps provided."""


def assess_contact(contact: dict, notes: list[dict], tasks: list[dict]) -> ContactAssessment:
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    # Build the context block
    name = f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip() or "(no name)"
    now  = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Sort notes newest-first, take MAX_NOTES
    sorted_notes = sorted(notes, key=lambda n: n.get("dateAdded", ""), reverse=True)[:MAX_NOTES]
    notes_text = "\n".join(
        f"  [{n.get('dateAdded', '?')[:10]}] {n.get('body', '').strip()}"
        for n in sorted_notes
    ) or "  (no notes)"

    sorted_tasks = sorted(tasks, key=lambda t: t.get("dueDate", ""), reverse=True)[:MAX_TASKS]
    tasks_text = "\n".join(
        f"  [{t.get('dueDate', '?')[:10]}] {'✓' if t.get('completed') else '○'} {t.get('title', '').strip()}"
        for t in sorted_tasks
    ) or "  (no tasks)"

    current_tags = [t for t in contact.get("tags", []) if t in VALID_STATUSES]
    date_added   = contact.get("dateAdded", "unknown")[:10]
    last_updated = contact.get("dateUpdated", "unknown")[:10]

    user_message = f"""Today: {now}

Contact: {name}
Email: {contact.get('email', 'n/a')}
Phone: {contact.get('phone', 'n/a')}
Added: {date_added}
Last updated: {last_updated}
Current status tag(s): {', '.join(current_tags) if current_tags else 'none'}

--- Notes (most recent first) ---
{notes_text}

--- Tasks ---
{tasks_text}

Assess this contact's engagement level and assign one status from the list."""

    response = client.messages.parse(
        model="claude-opus-4-6",
        max_tokens=1024,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
        output_format=ContactAssessment,
    )

    return response.parsed_output


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not ANTHROPIC_KEY:
        print("ERROR: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Starting weekly contact review …")
    contacts = get_all_contacts()
    total    = len(contacts)
    print(f"Found {total} contact(s) to review.\n")

    results = {"hot": 0, "warm": 0, "cold": 0, "inactive": 0, "closed": 0, "errors": 0}

    for i, contact in enumerate(contacts, 1):
        name = (
            f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip()
            or contact.get("email", contact["id"])
        )
        print(f"[{i}/{total}] {name}")

        try:
            notes = get_notes(contact["id"])
            tasks = get_tasks(contact["id"])

            assessment = assess_contact(contact, notes, tasks)

            # Validate the returned status
            status = assessment.status.strip().lower()
            if status not in VALID_STATUSES:
                print(f"    ⚠ Claude returned unexpected status '{status}', defaulting to status:cold")
                status = "status:cold"

            # Apply to GHL
            update_contact_tags(contact["id"], contact.get("tags", []), status)

            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            note_body = (
                f"[Weekly AI Review — {timestamp}]\n"
                f"Status set to: {status}\n\n"
                f"Assessment: {assessment.reasoning}\n\n"
                f"Recommended action: {assessment.recommended_action}"
            )
            add_note(contact["id"], note_body)

            bucket = status.replace("status:", "")
            results[bucket] = results.get(bucket, 0) + 1
            print(f"    → {status}")

        except Exception as exc:
            print(f"    ✗ Error: {exc}")
            results["errors"] += 1

        # Small pause to stay well within GHL rate limits
        time.sleep(0.3)

    print(f"\n{'─'*50}")
    print(f"Review complete — {total} contacts processed")
    print(f"  hot:      {results['hot']}")
    print(f"  warm:     {results['warm']}")
    print(f"  cold:     {results['cold']}")
    print(f"  inactive: {results['inactive']}")
    print(f"  closed:   {results['closed']}")
    print(f"  errors:   {results['errors']}")
    print(f"{'─'*50}\n")


if __name__ == "__main__":
    main()
