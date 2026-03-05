"""
DumpDynasty Marketing Agent
============================
Orchestrates lead scraping via Apify and CRM ingestion via GoHighLevel.

Usage:
    python agent.py --location "Houston, TX" --max-leads 100
    python agent.py --location "Dallas, TX" --search "construction,contractors,roofing"
"""

import argparse
import json
import sys
from datetime import datetime

import apify_integration as apify
import ghl_integration as ghl


# Default search terms relevant to Dump Dynasty's target customers
DEFAULT_SEARCH_TERMS = [
    "construction companies",
    "general contractors",
    "roofing companies",
    "renovation companies",
    "home builders",
    "demolition companies",
    "landscaping companies",
    "property management companies",
]


def run(location: str, search_terms: list[str], max_leads: int, dry_run: bool = False) -> dict:
    """
    Main agent entry point.

    1. Scrapes leads from Apify (Google Maps)
    2. Filters leads that have at least a phone or email
    3. Upserts each lead into GoHighLevel
    4. Returns a summary report

    Args:
        location:     City/region to target, e.g. "Houston, TX"
        search_terms: List of business types to search
        max_leads:    Max results to pull per search term
        dry_run:      If True, scrape but don't push to GHL

    Returns:
        Summary dict with created/updated/skipped counts and any errors
    """
    print(f"\n{'='*60}")
    print(f"  DumpDynasty Marketing Agent")
    print(f"  Location : {location}")
    print(f"  Terms    : {', '.join(search_terms)}")
    print(f"  Max leads: {max_leads}")
    print(f"  Dry run  : {dry_run}")
    print(f"  Started  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # --- Step 1: Scrape leads ---
    leads = apify.scrape_google_maps_leads(
        search_terms=search_terms,
        location=location,
        max_results=max_leads,
    )

    if not leads:
        print("[Agent] No leads found. Exiting.")
        return {"scraped": 0, "created": 0, "updated": 0, "skipped": 0, "errors": []}

    # --- Step 2: Filter actionable leads ---
    actionable = [l for l in leads if l.get("phone") or l.get("email")]
    skipped_count = len(leads) - len(actionable)
    print(f"[Agent] {len(leads)} leads scraped | {len(actionable)} actionable | {skipped_count} skipped (no contact info)")

    if dry_run:
        print("\n[Agent] DRY RUN — printing first 5 leads, not pushing to GHL:\n")
        for lead in actionable[:5]:
            print(json.dumps(lead, indent=2))
        return {
            "scraped": len(leads),
            "actionable": len(actionable),
            "created": 0,
            "updated": 0,
            "skipped": skipped_count,
            "errors": [],
        }

    # --- Step 3: Upsert into GoHighLevel ---
    created = 0
    updated = 0
    errors = []

    for i, lead in enumerate(actionable, 1):
        try:
            _contact, was_created = ghl.upsert_contact(lead)
            if was_created:
                created += 1
                status = "CREATED"
            else:
                updated += 1
                status = "UPDATED"
            print(f"[GHL] ({i}/{len(actionable)}) {status}: {lead['name']}")
        except Exception as exc:
            error_msg = f"Failed to upsert '{lead.get('name')}': {exc}"
            print(f"[GHL] ERROR — {error_msg}")
            errors.append(error_msg)

    summary = {
        "scraped": len(leads),
        "actionable": len(actionable),
        "created": created,
        "updated": updated,
        "skipped": skipped_count,
        "errors": errors,
    }

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"  Scraped  : {summary['scraped']}")
    print(f"  Created  : {summary['created']}")
    print(f"  Updated  : {summary['updated']}")
    print(f"  Skipped  : {summary['skipped']}")
    print(f"  Errors   : {len(summary['errors'])}")
    print(f"  Finished : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    return summary


def main():
    parser = argparse.ArgumentParser(description="DumpDynasty Marketing Agent — Apify + GHL lead pipeline")
    parser.add_argument(
        "--location",
        required=True,
        help='Target city/region, e.g. "Houston, TX"',
    )
    parser.add_argument(
        "--search",
        default="",
        help="Comma-separated search terms (defaults to construction/contractor categories)",
    )
    parser.add_argument(
        "--max-leads",
        type=int,
        default=50,
        help="Max results per search term (default: 50)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape leads but do not push to GoHighLevel",
    )

    args = parser.parse_args()

    search_terms = [t.strip() for t in args.search.split(",") if t.strip()] if args.search else DEFAULT_SEARCH_TERMS

    summary = run(
        location=args.location,
        search_terms=search_terms,
        max_leads=args.max_leads,
        dry_run=args.dry_run,
    )

    # Non-zero exit if there were errors
    if summary.get("errors"):
        sys.exit(1)


if __name__ == "__main__":
    main()
