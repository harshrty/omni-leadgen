"""
Personalised Email Drafter using Claude.
Generates a tailored cold email for every lead in the export.
- If decision maker name + title is known → personalised to them directly
- Otherwise → personalised to the company/hiring context
Saves draft_subject + draft_email back to DB, then re-exports Excel.
"""
import re
import sqlite3
import time
from config import DB_PATH, ANTHROPIC_API_KEY

# ============================================================
#  OMNITHRIVE CONTEXT (loaded once, used in every prompt)
# ============================================================
OMNITHRIVE_CONTEXT = """
Company: Omnithrive Technologies
Tagline: AI Value Acceleration Studio
Core Promise: Turn failing or stalled AI initiatives into measurable profits within 90 days.

Key differentiators:
- ROI-first: we guarantee measurable results, not demos
- Free 2-Day AI Opportunity Audit (no commitment, no cost) — this is the CTA
- Production-ready systems, not pilots or prototypes
- Custom-built for each client's workflows (no generic tools)
- Built-in change management & adoption — we don't disappear after deployment
- We only scale when value is proven

Tech stack we work with:
- Agentic AI: LangChain, LangGraph, AutoGen, CrewAI, LangFuse
- Automation: n8n, Zapier, Make (Integromat)
- LLMs: GPT-4, Claude, Llama, Mistral, Gemini

Ideal clients: Mid-to-large enterprises (200–2,000 employees) in Logistics, Manufacturing,
Healthcare, Finance, SaaS, Retail — anywhere process inefficiency is costing millions.

Services:
1. AI Opportunity Audit — 2 days, FREE
2. High-Impact MVP Build — 2-3 weeks, from $399
3. Value Proof + Scale Strategy — ongoing
4. Expert AI Developers on demand — $30/hr (LangChain, LangGraph, AutoGen, CrewAI)

CTA: Book a free AI Opportunity Audit at cal.com/omnithrivetech-ceo
Contact: admin@omnithrivetech.com | WhatsApp: +91 97426 09264

Stat hooks to use:
- 75% of AI projects fail to deliver ROI (IBM CEO Study, 2025)
- 88% of AI pilots never reach production (CIO Magazine)
- We turn that around — production-ready in 90 days, or no fee
"""

PROMPT_WITH_DM = """You are a senior B2B outreach specialist writing a formal cold email on behalf of Omnithrive Technologies.

OMNITHRIVE CONTEXT:
{omnithrive}

TARGET LEAD:
- Decision Maker: {dm_name} ({dm_title})
- Company: {company}
- Industry: {industry}
- What they do: {description}
- Currently hiring for: {job_title}
- Tech stack / keywords from their JD: {keywords}
- Their annual budget for this hire: {salary_budget}

JOB DESCRIPTION EXCERPT:
{job_description}

MANDATORY RULES — follow every one without exception:
1. SALUTATION: Start with "Dear {dm_name}," (use their actual name, never generic)
2. PERSONALIZATION: Read the JD excerpt above. Reference 1-2 specific responsibilities or technologies from it to show you understand their exact problem. Do NOT be generic.
3. SALARY PITCH: State clearly that Omnithrive can deliver equivalent AI capabilities for 1/10th of what they would pay a full-time hire. Their budget is {salary_budget}/year — we cost approximately {salary_tenth}. Weave this naturally into the email.
4. STAT: Include exactly one stat from below to create urgency:
   - "75% of AI projects fail to deliver ROI (IBM CEO Study, 2025)"
   - "88% of AI pilots never reach production (CIO Magazine)"
5. CTA: End with an offer of our complimentary 2-Day AI Opportunity Audit. Include: cal.com/omnithrivetech-ceo
6. TONE: Formal, professional, and respectful. No casual language, no slang.
7. CLOSING: Close with "Warm regards," followed by your name and title.
8. LENGTH: Strictly 230 to 250 words. Count carefully. Not 229, not 251.
9. SUBJECT LINE: Must be under 60 characters. Make it specific to {company} or their {job_title} role — curiosity-driven and intriguing, not salesy. Think: a sharp observation about their situation, not a pitch.
   Good examples: "A thought on {company}'s AI build" | "{company}'s AI hiring - a perspective" | "Re: your {job_title} search"
   AVOID these spam/promotion trigger words in subject: free, guaranteed, limited time, act now, offer, deal, click, earn, discount, prize, winner, congratulations, urgent, no cost, 100%, !!!, $$$
10. PUNCTUATION: Do NOT use em-dashes (--) or en-dashes. Use plain hyphens (-) instead. Use straight quotes only. Keep punctuation simple and natural.

Respond ONLY in this exact format:
SUBJECT: <subject line>
EMAIL:
<email body>"""

PROMPT_WITHOUT_DM = """You are a senior B2B outreach specialist writing a formal cold email on behalf of Omnithrive Technologies.

OMNITHRIVE CONTEXT:
{omnithrive}

TARGET LEAD:
- Company: {company}
- Industry: {industry}
- What they do: {description}
- Currently hiring for: {job_title}
- Tech stack / keywords from their JD: {keywords}
- Their annual budget for this hire: {salary_budget}

JOB DESCRIPTION EXCERPT:
{job_description}

MANDATORY RULES — follow every one without exception:
1. SALUTATION: Do NOT use "Dear Hiring Manager". Instead use "Dear {company} Team," — always address the company by name.
2. PERSONALIZATION: Read the JD excerpt above. Reference 1-2 specific responsibilities or technologies from it to show you understand their exact challenge. Do NOT be generic.
3. SALARY PITCH: State clearly that Omnithrive can deliver equivalent AI capabilities for 1/10th of what they would pay a full-time hire. Their budget is {salary_budget}/year — we cost approximately {salary_tenth}. Weave this naturally into the email.
4. STAT: Include exactly one stat from below to create urgency:
   - "75% of AI projects fail to deliver ROI (IBM CEO Study, 2025)"
   - "88% of AI pilots never reach production (CIO Magazine)"
5. CTA: End with an offer of our complimentary 2-Day AI Opportunity Audit. Include: cal.com/omnithrivetech-ceo
6. TONE: Formal, professional, and respectful. No casual language, no slang.
7. CLOSING: Close with "Warm regards," followed by your name and title.
8. LENGTH: Strictly 230 to 250 words. Count carefully. Not 229, not 251.
9. SUBJECT LINE: Must be under 60 characters. Make it specific to {company} or their {job_title} role — curiosity-driven and intriguing, not salesy. Think: a sharp observation about their situation, not a pitch.
   Good examples: "A thought on {company}'s AI build" | "{company}'s AI hiring - a perspective" | "Re: your {job_title} search"
   AVOID these spam/promotion trigger words in subject: free, guaranteed, limited time, act now, offer, deal, click, earn, discount, prize, winner, congratulations, urgent, no cost, 100%, !!!, $$$
10. PUNCTUATION: Do NOT use em-dashes (--) or en-dashes. Use plain hyphens (-) instead. Use straight quotes only. Keep punctuation simple and natural.

Respond ONLY in this exact format:
SUBJECT: <subject line>
EMAIL:
<email body>"""


def sanitize_text(text: str) -> str:
    """Replace AI-telltale punctuation with plain equivalents."""
    # Em-dash and en-dash -> plain hyphen (with spaces preserved)
    text = text.replace("\u2014", "-")   # em-dash
    text = text.replace("\u2013", "-")   # en-dash
    # Smart quotes -> straight quotes
    text = text.replace("\u2018", "'").replace("\u2019", "'")   # left/right single
    text = text.replace("\u201c", '"').replace("\u201d", '"')   # left/right double
    # Ellipsis character -> three dots
    text = text.replace("\u2026", "...")
    return text


def get_salary_pitch(salary_raw):
    """
    Returns (budget_str, tenth_str) for the 1/10th price pitch.
    Tries to parse a number from the stored salary string.
    Falls back to $100,000 / $10,000 if nothing usable is found.
    """
    if salary_raw:
        # Normalise K -> 000 before extracting digits
        normalised = re.sub(r'(\d+)\s*[kK]\b', lambda m: str(int(m.group(1)) * 1000), salary_raw)
        nums = re.findall(r'\d[\d,]*', normalised)
        for n in nums:
            try:
                val = int(n.replace(",", ""))
                if 30000 <= val <= 1000000:  # plausible annual salary
                    tenth = val // 10
                    return "${:,}".format(val), "${:,}".format(tenth)
            except ValueError:
                continue
    return "$100,000", "$10,000"


def generate_email(client, lead):
    company = lead.get("company_name", "")
    dm_name = (lead.get("decision_maker_name") or "").strip()
    dm_title = (lead.get("decision_maker_title") or "").strip()
    description = (lead.get("company_description") or "").strip()
    industry = (lead.get("company_industry") or "").strip()
    job_title = (lead.get("job_title") or "").strip()
    keywords = (lead.get("tech_keywords") or "").strip()
    job_desc = (lead.get("job_description") or "").strip()
    salary_budget, salary_tenth = get_salary_pitch(lead.get("salary", ""))

    jd_excerpt = job_desc[:800] if job_desc else "(No job description available — use company info above to personalise.)"

    if dm_name:
        prompt = PROMPT_WITH_DM.format(
            omnithrive=OMNITHRIVE_CONTEXT,
            dm_name=dm_name,
            dm_title=dm_title or "Decision Maker",
            company=company,
            industry=industry or "Technology",
            description=description or "an enterprise company",
            job_title=job_title,
            keywords=keywords[:300] if keywords else "AI/ML",
            salary_budget=salary_budget,
            salary_tenth=salary_tenth,
            job_description=jd_excerpt,
        )
    else:
        prompt = PROMPT_WITHOUT_DM.format(
            omnithrive=OMNITHRIVE_CONTEXT,
            company=company,
            industry=industry or "Technology",
            description=description or "an enterprise company",
            job_title=job_title,
            keywords=keywords[:300] if keywords else "AI/ML",
            salary_budget=salary_budget,
            salary_tenth=salary_tenth,
            job_description=jd_excerpt,
        )

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    subject, email_body = "", ""

    lines = raw.split("\n")
    body_lines = []
    in_body = False

    for line in lines:
        if line.startswith("SUBJECT:"):
            subject = line.replace("SUBJECT:", "").strip()
        elif line.startswith("EMAIL:"):
            in_body = True
        elif in_body:
            body_lines.append(line)

    email_body = "\n".join(body_lines).strip()
    return sanitize_text(subject), sanitize_text(email_body)


def run():
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set in .env")
        return

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Fetch all candidates, then pick ONE per company (best-quality lead).
    # Skip any company that already has a drafted email on any of its rows.
    all_candidates = conn.execute(
        """SELECT * FROM leads
           WHERE decision_maker_email IS NOT NULL
           AND decision_maker_email != ''
           AND (draft_email IS NULL OR draft_email = '')
           AND company_name NOT IN (
               SELECT DISTINCT company_name FROM leads
               WHERE draft_email IS NOT NULL AND draft_email != ''
           )
           ORDER BY company_name"""
    ).fetchall()

    # Pick best row per company: score = DM name (3) + has JD (2) + has desc (1)
    best_per_company = {}
    for row in all_candidates:
        r = dict(row)
        key = r["company_name"]
        score = (
            (3 if (r.get("decision_maker_name") or "").strip() else 0) +
            (2 if (r.get("job_description") or "").strip() else 0) +
            (1 if (r.get("company_description") or "").strip() else 0)
        )
        if key not in best_per_company or score > best_per_company[key][0]:
            best_per_company[key] = (score, r)

    rows = [v[1] for v in sorted(best_per_company.values(), key=lambda x: x[1]["company_name"])]

    if not rows:
        print("All leads already have draft emails. Nothing to do.")
        conn.close()
        return

    total = len(rows)
    print("Drafting emails for " + str(total) + " leads using Claude Sonnet...\n")

    done = 0
    failed = 0

    for i, lead in enumerate(rows):
        company = lead["company_name"]
        dm_name = (lead.get("decision_maker_name") or "").strip()
        prefix = "[" + str(i + 1) + "/" + str(total) + "] " + company

        try:
            subject, body = generate_email(client, lead)
            if subject and body:
                conn.execute(
                    "UPDATE leads SET draft_subject = ?, draft_email = ? WHERE id = ?",
                    (subject, body, lead["id"])
                )
                conn.commit()
                done += 1
                dm_label = " -> " + dm_name if dm_name else " -> (no DM)"
                print(prefix + dm_label)
            else:
                failed += 1
                print(prefix + " FAILED (empty response)")
        except Exception as e:
            failed += 1
            print(prefix + " ERROR: " + str(e)[:60])

        time.sleep(0.5)

    conn.close()
    print("\nDone. Drafted: " + str(done) + " | Failed: " + str(failed))

    if done > 0:
        print("\nRe-exporting Excel with draft emails...")
        from export_xlsx import export
        export()


if __name__ == "__main__":
    run()
