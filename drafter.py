import json
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL, COMPANY_NAME, COMPANY_PITCH
from db import get_leads_by_status, update_lead, get_stats


SYSTEM_MSG = (
    "You are a B2B sales copywriter. You write short, "
    "direct, personalized cold emails. Always respond "
    "with valid JSON only, no markdown fences. "
    "JSON keys must be: subject, email, linkedin_note"
)


def build_prompt(lead):
    parts = [
        "You are writing a cold email on behalf of " + COMPANY_NAME + ",",
        "a company described as: " + COMPANY_PITCH,
        "",
        'The target company "' + lead["company_name"] + '" is currently hiring for:',
        '"' + lead["job_title"] + '"',
        "",
        "Here is context from their job posting:",
        '"' + lead.get("job_description", "AI-related role") + '"',
        "",
        "The email is going to " + lead["contact_name"] + ", who is the " + lead["contact_title"] + ".",
        "",
        "Write a short, personalized cold email (under 150 words) that:",
        "1. Acknowledges they are actively building their AI team",
        "2. Offers our AI development services as a faster alternative to hiring",
        "3. Mentions specific AI capabilities relevant to their job posting",
        "4. Ends with a soft call-to-action to book a 15-min call",
        "5. Sounds like a real human wrote it, not a template",
        "",
        "Also write:",
        "- A subject line (under 50 characters)",
        "- A short LinkedIn connection note (under 280 characters)",
        "",
        'Respond ONLY in valid JSON: {"subject": "...", "email": "...", "linkedin_note": "..."}',
    ]
    return "\n".join(parts)


def draft_email(lead):
    if not GROQ_API_KEY:
        print("ERROR: GROQ_API_KEY not set in .env")
        return None

    client = Groq(api_key=GROQ_API_KEY)

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_MSG},
                {"role": "user", "content": build_prompt(lead)},
            ],
            temperature=0.7,
            max_tokens=500,
        )

        raw = response.choices[0].message.content.strip()

        # Strip markdown fences if present
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

        result = json.loads(raw)
        return result

    except json.JSONDecodeError:
        print("    WARNING: LLM returned invalid JSON.")
        return None
    except Exception as e:
        print("    ERROR: Groq API call failed: " + str(e))
        return None


def run_drafter():
    print("")
    print("=" * 50)
    print("  DRAFTER: Generating personalized cold emails")
    print("=" * 50)

    leads = get_leads_by_status("enriched")
    if not leads:
        print("No enriched leads to draft for.")
        return 0

    count = len(leads)
    print("Found " + str(count) + " leads to draft emails for.")
    drafted = 0

    for lead in leads:
        company = lead["company_name"]
        contact = lead["contact_name"]
        print("  Drafting for " + contact + " at " + company + "...")

        result = draft_email(lead)

        if result:
            update_lead(
                lead["id"],
                draft_subject=result.get("subject", ""),
                draft_email=result.get("email", ""),
                draft_linkedin_note=result.get("linkedin_note", ""),
                status="drafted",
            )
            drafted += 1
            print("    DONE: Subject: " + result.get("subject", "N/A"))
        else:
            print("    FAILED: Could not generate draft.")

    print("Drafter done: " + str(drafted) + " emails drafted.")
    get_stats()
    return drafted


if __name__ == "__main__":
    run_drafter()