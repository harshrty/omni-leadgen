import os
from dotenv import load_dotenv

load_dotenv()

# --- API Keys ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
SNOV_USER_ID = os.getenv("SNOV_USER_ID", "")
SNOV_API_SECRET = os.getenv("SNOV_API_SECRET", "")
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")

# --- Scraper Settings ---
SEARCH_QUERIES = [
    "AI Developer",
    "AI Engineer",
    "Machine Learning Engineer",
    "AI Software Engineer",
    "GenAI Developer",
    "LLM Engineer",
    "Deep Learning Engineer",
    "NLP Engineer",
    "Computer Vision Engineer",
    "AI Research Engineer",
    "MLOps Engineer",
    "Full Stack AI Developer",
]

# Regions to search: USA + major European markets
SEARCH_LOCATIONS = [
    "United States",
    "United Kingdom",
    "Germany",
    "France",
    "Netherlands",
    "Ireland",
    "Switzerland",
    "Sweden",
    "Spain",
    "Italy",
    "Poland",
    "Denmark",
    "Belgium",
    "Austria",
    "Norway",
    "Finland",
    "Portugal",
]

# LinkedIn time filter: r86400=24h, r259200=72h, r604800=1week
TIME_FILTER = "r86400"  # Past 24 hours

MAX_PAGES_PER_QUERY = 2  # Each page ~ 25 jobs

# --- Anti-Detection Settings ---
MIN_DELAY = 4
MAX_DELAY = 10
MAX_LEADS_PER_RUN = 500

# --- Enricher Settings ---
GROQ_MODEL = "llama-3.3-70b-versatile"

# Decision maker titles to look for
TARGET_TITLES = [
    "CTO", "Chief Technology Officer",
    "CEO", "Chief Executive Officer",
    "Founder", "Co-Founder",
    "VP of Engineering", "Vice President Engineering",
    "Head of Engineering", "Head of AI",
    "VP Technology", "Director of Engineering",
    "Chief AI Officer", "Head of Machine Learning",
]

# --- Company Info for Outreach ---
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
        "GROQ_API_KEY": bool(GROQ_API_KEY),
        "SNOV_USER_ID": bool(SNOV_USER_ID),
        "SNOV_API_SECRET": bool(SNOV_API_SECRET),
        "HUNTER_API_KEY": bool(HUNTER_API_KEY),
    }
    print("")
    print("--- API Key Status ---")
    for name, loaded in keys.items():
        status = "OK" if loaded else "MISSING (optional)"
        print("  " + name + ": " + status)
    print()
    return keys


if __name__ == "__main__":
    check_keys()