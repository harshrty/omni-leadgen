"""
Personalised Email Drafter using Claude - IMPLEMENTATION PARTNER VERSION
Generates tailored cold emails positioning Omnithrive as an AI implementation and outsourcing partner.
- If decision maker name + title is known -> personalised to them directly
- Otherwise -> personalised to the company/context
Saves draft_subject + draft_email back to DB, then re-exports Excel.
"""
import os
import re
import time
from config import (
    ANTHROPIC_API_KEY, FOUNDER_NAME, FOUNDER_TITLE,
    COMPANY_NAME, COMPANY_WEBSITE, FROM_EMAIL,
)
from db import get_all_leads, update_lead

# ============================================================
#  OMNITHRIVE CONTEXT — loaded from company_brief.txt if present
# ============================================================
_BRIEF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "company_brief.txt")


def load_company_context() -> str:
    if os.path.exists(_BRIEF_PATH):
        try:
            with open(_BRIEF_PATH, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if text:
                return text
        except Exception:
            pass
    return _DEFAULT_CONTEXT


def _build_default_context() -> str:
    name    = COMPANY_NAME    or "Your Company"
    founder = FOUNDER_NAME    or "the Founder"
    title   = FOUNDER_TITLE   or "Founder & CEO"
    website = COMPANY_WEBSITE or ""
    contact = FROM_EMAIL      or ""
    pitch   = ""
    # Try to pull pitch from company_config.json
    try:
        from company_config import load_config as _lc
        pitch = _lc().get("company_pitch", "")
    except Exception:
        pass

    lines = [
        "Company: " + name,
        (title + ": " + founder) if founder else "",
        ("Website: " + website) if website else "",
        ("Contact: " + contact) if contact else "",
        "",
        ("Pitch: " + pitch) if pitch else "",
    ]
    return "\n".join(l for l in lines if l is not None)


_DEFAULT_CONTEXT = _build_default_context()

OMNITHRIVE_CONTEXT = load_company_context()

# ============================================================
#  PROMPT: WITH decision maker name
# ============================================================
PROMPT_WITH_DM = """You are writing a formal cold outreach email on behalf of {founder_name}, {founder_title} of {company_name}.

COMPANY CONTEXT:
{omnithrive}

TARGET LEAD:
- Decision Maker: {dm_name} ({dm_title})
- Company: {company}
- Industry: {industry}
- What they do: {description}
- Currently hiring for: {job_title}
- Tech stack / keywords from their JD: {keywords}

JOB DESCRIPTION EXCERPT:
{job_description}

INSTRUCTIONS — write the email in the EXACT structure below. Do not skip or reorder any section.

---

SECTION 1 - OPENING (2 sentences):
Start with: "We have yet to be properly introduced, I am {founder_name}, {founder_title} of {company_name}."
Then in one sentence: say you came across {company}'s {job_title} opening and it prompted you to reach out - not because you are selling recruitment services, but because the role description signals something larger: an AI initiative that needs execution support.

SECTION 2 - THE AI ROI CRISIS HOOK (2-3 sentences):
State that 75% of AI projects fail to deliver expected ROI and 88% of pilots never reach production. Most enterprises are under pressure to demonstrate AI results but lack the internal capacity to execute reliably. Then transition: {company_name} exists to solve this exact problem - we are an AI implementation and outsourcing partner built around one metric: measurable business results within 90 days.

SECTION 3 - COMPANY POSITIONING (3-4 sentences):
Introduce {company_name} as an AI implementation partner. We do not build AI for the sake of AI - we build production-grade GenAI and agentic AI automations that pay for themselves within 90 days. Emphasise: we take full or partial ownership of AI initiatives, automation workflows, and transformation projects from concept to production. Not consulting. Not staff augmentation. Strategic implementation partnership.

SECTION 4 - "Why this matters to {company}" (use this as a heading, substituting the actual company name):
Open with 2-3 sentences connecting their {job_title} search to a broader AI execution challenge. Reference specific technical requirements from their JD excerpt (e.g., specific LLM frameworks, deployment environments, MLOps requirements, automation needs). Show that you have read their job description and understand the underlying initiative.

Then write 3-4 sentences describing how {company_name} would approach this as an implementation partner - not by placing a developer, but by taking ownership of the project end-to-end. Reference the same technical areas from their JD, but frame it as "we build and deliver this" rather than "we have engineers who know this." Be specific about project execution capability, not just technical knowledge.

SECTION 5 - THE 90-DAY AI ROI BLUEPRINT (introduce with: "Here is how we typically engage with enterprises facing similar AI execution challenges:"):
Describe the three-phase approach in exactly this format:

**Phase 1 - AI Opportunity Audit (2 days, FREE):** We map your highest-cost workflows, quantify manual time and error rates, project AI impact per process, and deliver a ranked implementation roadmap with ROI model - before you invest a dollar.

**Phase 2 - High-Impact MVP Build (2-3 weeks, from $399):** We build production-ready automation for 1-2 highest-ROI use cases identified in Phase 1. Not prototypes - deployable systems with KPI baselines set before build. Examples: AP automation, lead scoring, claims processing, ticket routing.

**Phase 3 - Value Proof + Scale Strategy (Ongoing):** Before/after metrics comparison, ROI dashboards for executive reporting, change management and team adoption support. We only expand when value is proven.

SECTION 6 - STRATEGIC PARTNERSHIP VALUE (3-4 sentences):
Explain what sets {company_name} apart from traditional consulting or staffing models. Four key points:
1. Full-cycle execution: requirements analysis to production deployment - you get delivered systems, not recommendations
2. Enterprise-grade standards: SOC 2, GDPR, HIPAA-ready architectures with complete documentation
3. Ownership transfer: production-ready code and systems you fully own - no vendor lock-in
4. Cost efficiency: 60-75% savings compared to Western in-house development, with transparent sprint planning and milestone tracking

SECTION 7 - INDUSTRY CONTEXT (2-3 sentences):
Acknowledge their specific business context ({industry}, {description}). Show you understand the operational pressures in their environment - e.g., process efficiency, speed to market, compliance requirements, or cost control. Draw a direct connection between how they measure success and how {company_name} is built around the same outcomes-driven premise.

SECTION 8 - SOFT CTA (follow this structure closely):
Start with: "I am not asking for a long conversation. Just 20 minutes."
Then say you will walk them through: a free 2-day AI Opportunity Audit we would conduct for {company}, examples of production systems we have deployed in comparable contexts, and how we structure project ownership and deliverables to ensure you get measurable ROI within 90 days.
End with: "Would you be open to a brief call this week or next?"

SECTION 9 - CLOSING:
Close with exactly:
Best regards,
{founder_name}
{founder_title}, {company_name}
{company_website}
{contact_email}

---

HARD RULES:
- ADDRESS: Start with "Dear {dm_name}," on the very first line
- TONE: Formal, authoritative, peer-to-peer. Strategic partner, not vendor. Not salesy. Not sycophantic. No filler phrases like "I hope this finds you well."
- POSITIONING: Always frame as "we build and deliver projects" not "we provide developers." Implementation partner, not staffing agency.
- SPECIFICITY: Every technical reference must come from the actual JD excerpt above. Do not invent requirements.
- PUNCTUATION: No em-dashes or en-dashes. Use plain hyphens (-). Use straight quotes only.
- LENGTH: 480 to 560 words for the email body. Count carefully.

Respond ONLY in this exact format:
EMAIL:
<email body>"""


# ============================================================
#  PROMPT: WITHOUT decision maker name
# ============================================================
PROMPT_WITHOUT_DM = """You are writing a formal cold outreach email on behalf of {founder_name}, {founder_title} of {company_name}.

COMPANY CONTEXT:
{omnithrive}

TARGET LEAD:
- Company: {company}
- Industry: {industry}
- What they do: {description}
- Currently hiring for: {job_title}
- Tech stack / keywords from their JD: {keywords}

JOB DESCRIPTION EXCERPT:
{job_description}

INSTRUCTIONS — write the email in the EXACT structure below. Do not skip or reorder any section.

---

SECTION 1 - OPENING (2 sentences):
Start with: "I am {founder_name}, {founder_title} of {company_name}."
Then in one sentence: say you came across {company}'s {job_title} opening and it prompted you to reach out - not because you are selling recruitment services, but because the role description signals something larger: an AI initiative that needs execution support.

SECTION 2 - THE AI ROI CRISIS HOOK (2-3 sentences):
State that 75% of AI projects fail to deliver expected ROI and 88% of pilots never reach production. Most enterprises are under pressure to demonstrate AI results but lack the internal capacity to execute reliably. Then transition: {company_name} exists to solve this exact problem - we are an AI implementation and outsourcing partner built around one metric: measurable business results within 90 days.

SECTION 3 - COMPANY POSITIONING (3-4 sentences):
Introduce {company_name} as an AI implementation partner. We do not build AI for the sake of AI - we build production-grade GenAI and agentic AI automations that pay for themselves within 90 days. Emphasise: we take full or partial ownership of AI initiatives, automation workflows, and transformation projects from concept to production. Not consulting. Not staff augmentation. Strategic implementation partnership.

SECTION 4 - "Why this matters to {company}" (use this as a heading, substituting the actual company name):
Open with 2-3 sentences connecting their {job_title} search to a broader AI execution challenge. Reference specific technical requirements from their JD excerpt (e.g., specific LLM frameworks, deployment environments, MLOps requirements, automation needs). Show that you have read their job description and understand the underlying initiative.

Then write 3-4 sentences describing how {company_name} would approach this as an implementation partner - not by placing a developer, but by taking ownership of the project end-to-end. Reference the same technical areas from their JD, but frame it as "we build and deliver this" rather than "we have engineers who know this." Be specific about project execution capability, not just technical knowledge.

SECTION 5 - THE 90-DAY AI ROI BLUEPRINT (introduce with: "Here is how we typically engage with enterprises facing similar AI execution challenges:"):
Describe the three-phase approach in exactly this format:

**Phase 1 - AI Opportunity Audit (2 days, FREE):** We map your highest-cost workflows, quantify manual time and error rates, project AI impact per process, and deliver a ranked implementation roadmap with ROI model - before you invest a dollar.

**Phase 2 - High-Impact MVP Build (2-3 weeks, from $399):** We build production-ready automation for 1-2 highest-ROI use cases identified in Phase 1. Not prototypes - deployable systems with KPI baselines set before build. Examples: AP automation, lead scoring, claims processing, ticket routing.

**Phase 3 - Value Proof + Scale Strategy (Ongoing):** Before/after metrics comparison, ROI dashboards for executive reporting, change management and team adoption support. We only expand when value is proven.

SECTION 6 - STRATEGIC PARTNERSHIP VALUE (3-4 sentences):
Explain what sets {company_name} apart from traditional consulting or staffing models. Four key points:
1. Full-cycle execution: requirements analysis to production deployment - you get delivered systems, not recommendations
2. Enterprise-grade standards: SOC 2, GDPR, HIPAA-ready architectures with complete documentation
3. Ownership transfer: production-ready code and systems you fully own - no vendor lock-in
4. Cost efficiency: 60-75% savings compared to Western in-house development, with transparent sprint planning and milestone tracking

SECTION 7 - INDUSTRY CONTEXT (2-3 sentences):
Acknowledge their specific business context ({industry}, {description}). Show you understand the operational pressures in their environment - e.g., process efficiency, speed to market, compliance requirements, or cost control. Draw a direct connection between how they measure success and how {company_name} is built around the same outcomes-driven premise.

SECTION 8 - SOFT CTA (follow this structure closely):
Start with: "I am not asking for a long conversation. Just 20 minutes."
Then say you will walk them through: a free 2-day AI Opportunity Audit we would conduct for {company}, examples of production systems we have deployed in comparable contexts, and how we structure project ownership and deliverables to ensure you get measurable ROI within 90 days.
End with: "Would the leadership team at {company} be open to a brief exploratory call?"

SECTION 9 - CLOSING:
Close with exactly:
Best regards,
{founder_name}
{founder_title}, {company_name}
{company_website}
{contact_email}

---

HARD RULES:
- ADDRESS: Start with "Dear Hiring Team at {company}," on the very first line (since no specific DM is known)
- TONE: Formal, authoritative, addressing business leadership. Strategic partner, not vendor. Not salesy. Not sycophantic. No filler phrases.
- POSITIONING: Always frame as "we build and deliver projects" not "we provide developers." Implementation partner, not staffing agency.
- SPECIFICITY: Every technical reference must come from the actual JD excerpt above. Do not invent requirements.
- PUNCTUATION: No em-dashes or en-dashes. Use plain hyphens (-). Use straight quotes only.
- LENGTH: 480 to 560 words for the email body. Count carefully.

Respond ONLY in this exact format:
EMAIL:
<email body>"""


def sanitize_text(text):
    """Remove or replace problematic characters."""
    if not text:
        return ""
    text = text.replace("\u2014", "-")  # em dash
    text = text.replace("\u2013", "-")  # en dash
    text = text.replace("\u2018", "'")  # left single quote
    text = text.replace("\u2019", "'")  # right single quote / apostrophe
    text = text.replace("\u201c", '"')  # left double quote
    text = text.replace("\u201d", '"')  # right double quote
    text = text.replace("\u2026", "...")  # ellipsis
    text = re.sub(r"[^\x00-\x7F]+", "", text)  # remove any non-ASCII
    return text


def generate_email(client, lead):
    """Generate personalised email based on lead data."""
    company = lead["company_name"] or "your company"
    dm_name = (lead.get("decision_maker_name") or "").strip()
    dm_title = (lead.get("decision_maker_title") or "").strip()
    industry = lead.get("company_industry") or ""
    description = lead.get("company_description") or ""
    job_title = lead.get("job_title") or "AI/ML role"
    keywords = lead.get("tech_keywords") or ""
    job_desc = (lead.get("job_description") or "").strip()

    # Truncate JD to manageable size
    jd_excerpt = job_desc[:800] if job_desc else "(No job description available - use company info and industry context to personalise.)"

    _founder  = FOUNDER_NAME    or "the Founder"
    _ftitle   = FOUNDER_TITLE   or "Founder & CEO"
    _coname   = COMPANY_NAME    or "our company"
    _coweb    = COMPANY_WEBSITE or ""
    _contact  = FROM_EMAIL      or ""

    # Select the right prompt variant based on DM availability
    if dm_name:
        prompt = PROMPT_WITH_DM.format(
            omnithrive=OMNITHRIVE_CONTEXT,
            founder_name=_founder,
            founder_title=_ftitle,
            company_name=_coname,
            company_website=_coweb,
            contact_email=_contact,
            dm_name=dm_name,
            dm_title=dm_title or "Decision Maker",
            company=company,
            industry=industry or "Technology",
            description=description or "an enterprise company",
            job_title=job_title,
            keywords=keywords[:300] if keywords else "AI/ML",
            job_description=jd_excerpt,
        )
    else:
        prompt = PROMPT_WITHOUT_DM.format(
            omnithrive=OMNITHRIVE_CONTEXT,
            founder_name=_founder,
            founder_title=_ftitle,
            company_name=_coname,
            company_website=_coweb,
            contact_email=_contact,
            company=company,
            industry=industry or "Technology",
            description=description or "an enterprise company",
            job_title=job_title,
            keywords=keywords[:300] if keywords else "AI/ML",
            job_description=jd_excerpt,
        )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    email_body = ""

    lines = raw.split("\n")
    body_lines = []
    in_body = False

    for line in lines:
        if line.startswith("EMAIL:"):
            in_body = True
        elif in_body:
            body_lines.append(line)

    # If the response didn't include the EMAIL: marker, use the whole response
    if not body_lines:
        email_body = raw
    else:
        email_body = "\n".join(body_lines).strip()

    subject = company + "'s Implementation partner for your Agentic AI projects"

    return sanitize_text(subject), sanitize_text(email_body)


def run():
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set in .env")
        return

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Get all leads, skip already sent/opened/replied
    all_leads = get_all_leads()
    candidates = [
        l for l in all_leads
        if (l.get("decision_maker_email") or "").strip()
        and (l.get("status") or "scraped") not in ("sent", "opened", "replied")
    ]

    # Pick best row per company: score = DM name (3) + has JD (2) + has desc (1)
    best_per_company = {}
    for l in candidates:
        key = l["company_name"]
        score = (
            (3 if (l.get("decision_maker_name") or "").strip() else 0) +
            (2 if (l.get("job_description") or "").strip() else 0) +
            (1 if (l.get("company_description") or "").strip() else 0)
        )
        if key not in best_per_company or score > best_per_company[key][0]:
            best_per_company[key] = (score, l)

    rows = [v[1] for v in sorted(best_per_company.values(), key=lambda x: x[1]["company_name"])]

    if not rows:
        print("No leads to regenerate (all sent or no email address).")
        return

    total = len(rows)
    print("Regenerating emails for " + str(total) + " leads (skipping sent/opened/replied)...\n")

    done = 0
    failed = 0

    for i, lead in enumerate(rows):
        company = lead["company_name"]
        dm_name = (lead.get("decision_maker_name") or "").strip()
        prefix = "[" + str(i + 1) + "/" + str(total) + "] " + company

        try:
            subject, body = generate_email(client, lead)
            if subject and body:
                update_lead(lead["id"], draft_subject=subject, draft_email=body, status="drafted")
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

    print("\nDone. Drafted: " + str(done) + " | Failed: " + str(failed))

    if done > 0:
        print("\nRe-exporting Excel with draft emails...")
        from export_xlsx import export
        export()


if __name__ == "__main__":
    run()
