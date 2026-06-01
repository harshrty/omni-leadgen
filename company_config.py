"""
Parses a user-uploaded company context file using Claude and saves the result
to company_config.json. Imported by server.py for the /api/config/upload route.
"""
import json
import os
import re

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "company_config.json")

_EXTRACT_PROMPT = """You are extracting structured company configuration from a company profile document.

Read the document below and extract the following fields as a JSON object.
For any field not found in the document, use an empty string "" (or empty list [] for list fields).
For search_queries, search_locations, and target_titles — if not explicitly stated, use the defaults provided.

Fields to extract:
- company_name: string — full company name
- founder_name: string — name of the founder/CEO/primary contact who will send emails
- founder_title: string — their title (e.g. "Founder & CEO")
- company_website: string — website URL (e.g. "www.example.com")
- contact_email: string — primary contact email
- calendar_url: string — booking/calendar link (e.g. "cal.com/yourname")
- company_pitch: string — 2-4 sentence summary of what the company does and its value proposition
- roi_stats: list of strings — any ROI/failure/success statistics mentioned (e.g. "75% of AI projects fail")
- pricing_phase2: string — price for the initial paid engagement (e.g. "from $499")
- pricing_staffing: string — hourly rate for developer staffing (e.g. "$35/hour")
- search_queries: list of strings — job titles to search on LinkedIn (default: ["AI Engineer", "Machine Learning Engineer", "LLM Engineer", "GenAI Developer", "MLOps Engineer", "AI Software Engineer"])
- search_locations: list of strings — countries/regions to search (default: ["United States", "United Kingdom", "Germany", "France", "Netherlands"])
- target_titles: list of strings — decision maker titles to target (default: ["CTO", "CEO", "Founder", "Co-Founder", "VP of Engineering", "Head of AI", "Chief AI Officer"])

DOCUMENT:
{document}

Respond with ONLY valid JSON, no explanation, no markdown fences."""


def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from uploaded file (txt, docx, pdf)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"

    if ext == "txt":
        return file_bytes.decode("utf-8", errors="replace")

    if ext == "docx":
        try:
            import io
            from docx import Document
            doc = Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            raise ValueError("Could not read .docx file: " + str(e))

    if ext == "pdf":
        try:
            import io
            import pdfminer.high_level as pdfminer
            return pdfminer.extract_text(io.BytesIO(file_bytes))
        except ImportError:
            raise ValueError("pdfminer.six is required for PDF support: pip install pdfminer.six")
        except Exception as e:
            raise ValueError("Could not read .pdf file: " + str(e))

    raise ValueError("Unsupported file type: ." + ext + ". Please upload .txt, .docx, or .pdf")


def parse_company_context(file_text: str, anthropic_api_key: str) -> dict:
    """
    Send file text to Claude Haiku and extract structured company config.
    Returns a dict with all config fields.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=anthropic_api_key)
    prompt = _EXTRACT_PROMPT.format(document=file_text[:8000])

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if Claude wrapped the JSON
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        config = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError("Claude returned invalid JSON: " + str(e) + "\nRaw output: " + raw[:300])

    return _normalize(config)


def _normalize(config: dict) -> dict:
    """Ensure all expected keys exist with correct types."""
    defaults_lists = {
        "roi_stats": [],
        "search_queries": [
            "AI Engineer", "Machine Learning Engineer", "LLM Engineer",
            "GenAI Developer", "MLOps Engineer", "AI Software Engineer",
            "Deep Learning Engineer", "NLP Engineer", "AI Research Engineer",
        ],
        "search_locations": [
            "United States", "United Kingdom", "Germany", "France",
            "Netherlands", "Ireland", "Switzerland", "Sweden",
        ],
        "target_titles": [
            "CTO", "Chief Technology Officer", "CEO", "Chief Executive Officer",
            "Founder", "Co-Founder", "VP of Engineering", "Head of AI",
            "Chief AI Officer", "Head of Machine Learning",
        ],
    }
    str_keys = [
        "company_name", "founder_name", "founder_title", "company_website",
        "contact_email", "calendar_url", "company_pitch",
        "pricing_phase2", "pricing_staffing",
    ]

    result = {}
    for k in str_keys:
        result[k] = str(config.get(k, "") or "").strip()
    for k, default in defaults_lists.items():
        val = config.get(k)
        result[k] = val if isinstance(val, list) and val else default

    return result


def save_config(config: dict) -> None:
    """Write config dict to company_config.json."""
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def load_config() -> dict:
    """Load company_config.json, return empty dict if not found."""
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}
