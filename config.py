"""
Central configuration for the lead generation pipeline.
Loads API keys from .env and defines all settings.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- API Keys ---
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# --- Scraper Settings ---
SEARCH_QUERIES = [
    "AI Developer",
    "Full Stack AI Developer",
    "Machine Learning Engineer",
    "AI Software Engineer",
    "GenAI Developer",
    "LLM Engineer",
]

SEARCH_LOCATION = "United States"
MAX_PAGES_PER_QUERY = 2

# --- Anti-Detection Settings ---
MIN_DELAY = 4
MAX_DELAY = 10
SCROLL_MIN_DELAY = 1
SCROLL_MAX_DELAY = 3
MAX_LEADS_PER_RUN = 100

# --- Enricher Settings ---
TARGET_TITLES = [
    "CTO",
    "Chief Technology Officer",
    "Founder",
    "Co-Founder",
    "CEO",
    "VP of Engineering",
    "VP Engineering",
    "Head of Engineering",
    "Head of AI",
    "Chief AI Officer",
    "Director of Engineering",
]

APOLLO_DELAY = 2

# --- Drafter Settings ---
GROQ_MODEL = "llama-3.3-70b-versatile"

COMPANY_NAME = "Omnithrive Technologies"
COMPANY_PITCH = (
    "Omnithrive Technologies builds and deploys custom AI solutions, "
    "including full-stack AI applications, data pipelines, LLM integrations, "
    "and end-to-end machine learning systems. We help companies ship AI "
    "products in weeks instead of spending months hiring."
)

# --- Database ---
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leads.db")


def check_keys():
    keys = {
        "APOLLO_API_KEY": bool(APOLLO_API_KEY),
        "GROQ_API_KEY": bool(GROQ_API_KEY),
    }
    print("\n--- API Key Status ---")
    for name, loaded in keys.items():
        status = "OK" if loaded else "MISSING"
        print(f"  {name}: {status}")
    print()
    return keys


if __name__ == "__main__":
    check_keys()
    