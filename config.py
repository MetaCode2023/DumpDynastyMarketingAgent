import os
from dotenv import load_dotenv

load_dotenv()

APIFY_API_TOKEN = os.environ["APIFY_API_TOKEN"]
GHL_API_KEY = os.environ["GHL_API_KEY"]
GHL_LOCATION_ID = os.getenv("GHL_LOCATION_ID", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Apify actor IDs
GOOGLE_MAPS_ACTOR_ID = os.getenv("APIFY_GOOGLE_MAPS_ACTOR", "nwua9Gu5YrADL7ZDj")

# GHL API base URL
GHL_BASE_URL = "https://rest.gohighlevel.com/v1"
