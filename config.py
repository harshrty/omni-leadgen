import json
import os
from dotenv import load_dotenv

load_dotenv()


def _load_company_config() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "company_config.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _parse_list(env_val: str, default: list) -> list:
    if env_val:
        return [x.strip() for x in env_val.split("|") if x.strip()]
    return default


_cc = _load_company_config()

# --- API Keys ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# --- Free Provider Keys (all OpenAI-compatible) ---
# Get free keys at:
#   Cerebras  → cloud.cerebras.ai      (1M tokens/day, no card)
#   SambaNova → cloud.sambanova.ai     (unlimited rate-limited, no card)
#   Together  → api.together.ai        ($25 free credit, no card)
CEREBRAS_API_KEY  = os.getenv("CEREBRAS_API_KEY", "")
SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY", "")
TOGETHER_API_KEY  = os.getenv("TOGETHER_API_KEY", "")

# Multiple Hunter.io API keys (optional, 25 free credits each)
HUNTER_API_KEYS = []
for i in range(1, 21):
    key = os.getenv("HUNTER_API_KEY_" + str(i), "")
    if key:
        HUNTER_API_KEYS.append(key)
single_key = os.getenv("HUNTER_API_KEY", "")
if single_key and single_key not in HUNTER_API_KEYS:
    HUNTER_API_KEYS.insert(0, single_key)

# --- Company Identity (loaded from company_config.json, env fallback) ---
COMPANY_NAME    = _cc.get("company_name")    or os.getenv("COMPANY_NAME", "")
FOUNDER_NAME    = _cc.get("founder_name")    or os.getenv("FOUNDER_NAME", "")
FOUNDER_TITLE   = _cc.get("founder_title")   or os.getenv("FOUNDER_TITLE", "Founder & CEO")
COMPANY_WEBSITE = _cc.get("company_website") or os.getenv("COMPANY_WEBSITE", "")
COMPANY_PITCH   = _cc.get("company_pitch")   or os.getenv("COMPANY_PITCH", "")
CALENDAR_URL    = _cc.get("calendar_url")    or os.getenv("CALENDAR_URL", "")

# --- Scraper Settings ---
_DEFAULT_QUERIES = [
    "AI Developer", "AI Engineer", "Machine Learning Engineer",
    "AI Software Engineer", "GenAI Developer", "LLM Engineer",
    "Deep Learning Engineer", "NLP Engineer", "Computer Vision Engineer",
    "AI Research Engineer", "MLOps Engineer", "Full Stack AI Developer",
]
_DEFAULT_LOCATIONS = [
    "United States", "United Kingdom", "Germany", "France", "Netherlands",
    "Ireland", "Switzerland", "Sweden", "Spain", "Italy", "Poland",
    "Denmark", "Belgium", "Austria", "Norway", "Finland", "Portugal",
]
_DEFAULT_TITLES = [
    "CTO", "Chief Technology Officer",
    "CEO", "Chief Executive Officer",
    "Founder", "Co-Founder",
    "VP of Engineering", "Vice President Engineering",
    "Head of Engineering", "Head of AI",
    "VP Technology", "Director of Engineering",
    "Chief AI Officer", "Head of Machine Learning",
]

SEARCH_QUERIES   = _cc.get("search_queries")   or _parse_list(os.getenv("SEARCH_QUERIES"),   _DEFAULT_QUERIES)
SEARCH_LOCATIONS = _cc.get("search_locations") or _parse_list(os.getenv("SEARCH_LOCATIONS"), _DEFAULT_LOCATIONS)
TARGET_TITLES    = _cc.get("target_titles")    or _parse_list(os.getenv("TARGET_TITLES"),    _DEFAULT_TITLES)

TIME_FILTER = "r259200"  # 72 hours (was r86400 = 24h)
MAX_PAGES_PER_QUERY = 2
MIN_DELAY = 2
MAX_DELAY = 5
MAX_LEADS_PER_RUN = 500

# --- Enricher Settings ---
GROQ_MODEL = "llama-3.3-70b-versatile"

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leads.db")

# Always local SQLite — no remote database

# --- SMTP / Email Sending ---
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)
FROM_NAME = os.getenv("FROM_NAME", COMPANY_NAME or FOUNDER_NAME or "")

# --- IMAP / Reply Tracking ---
IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER", SMTP_USER)
IMAP_PASS = os.getenv("IMAP_PASS", SMTP_PASS)

# --- LinkedIn Scraping Credentials (dedicated/throwaway account recommended) ---
LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASS  = os.getenv("LINKEDIN_PASS", "")

# --- Scraper tuning ---
MAX_DESC_PER_RUN = int(os.getenv("MAX_DESC_PER_RUN", "150"))

# --- Notifications ---
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# --- Dashboard Server ---
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "5000"))
BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")


def check_keys():
    print("")
    print("--- Config Status ---")
    print("  GROQ_API_KEY:      " + ("OK" if GROQ_API_KEY else "MISSING"))
    print("  ANTHROPIC_API_KEY: " + ("OK" if ANTHROPIC_API_KEY else "MISSING"))
    print("  GEMINI_API_KEY:    " + ("OK" if GEMINI_API_KEY else "not set"))
    print("  CEREBRAS_API_KEY:  " + ("OK" if CEREBRAS_API_KEY else "not set"))
    print("  SAMBANOVA_API_KEY: " + ("OK" if SAMBANOVA_API_KEY else "not set"))
    print("  TOGETHER_API_KEY:  " + ("OK" if TOGETHER_API_KEY else "not set"))
    if HUNTER_API_KEYS:
        print("  HUNTER_API_KEYS:   " + str(len(HUNTER_API_KEYS)) + " keys (~" + str(len(HUNTER_API_KEYS) * 25) + " credits)")
    else:
        print("  HUNTER_API_KEYS:   none (free pipeline only)")
    print()


if __name__ == "__main__":
    check_keys()