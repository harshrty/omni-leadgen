# AI Lead-Gen Pipeline

An open-source, self-hosted B2B lead generation tool. It scrapes LinkedIn for companies actively hiring AI engineers (a strong buying signal), finds decision-maker contacts, generates personalized cold emails using Claude, and sends + tracks them through a web dashboard.

Anyone can run their own instance — just clone, configure credentials in `.env`, upload your company profile from the dashboard, and run.

---

## What It Does

1. **Scrapes LinkedIn** for AI/ML job postings (configurable roles + locations)
2. **Enriches leads** — finds company website, decision-maker name, email via DuckDuckGo + Hunter.io
3. **Drafts cold emails** — Claude Haiku writes formal, personalized emails using your company profile
4. **Dashboard** — review, edit, and send emails at `localhost:5000`
5. **Tracks opens + replies** — pixel tracking + IMAP polling

---

## Prerequisites

- Python 3.10+
- A Gmail account with [App Password](https://myaccount.google.com/apppasswords) enabled
- A LinkedIn account (dedicated/throwaway recommended)
- An [Anthropic API key](https://console.anthropic.com) (required for email drafting)
- Optional: [Groq](https://console.groq.com), [Hunter.io](https://hunter.io) keys for enrichment

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/harshrty/omni-leadgen.git
cd omni-leadgen
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Open `.env` and fill in:
- `ANTHROPIC_API_KEY` — required for email drafting
- `SMTP_USER` / `SMTP_PASS` — your Gmail + App Password
- `IMAP_USER` / `IMAP_PASS` — same Gmail for reply tracking
- `LINKEDIN_EMAIL` / `LINKEDIN_PASS` — LinkedIn scraping account
- `GROQ_API_KEY` — optional but recommended (free, speeds up enrichment)
- `HUNTER_API_KEY` — optional (25 free credits/month per key)

### 3. Start the dashboard

```bash
python server.py
```

Open [http://localhost:5000](http://localhost:5000)

### 4. Set up your company profile

Click **⚙ Setup** in the top-right corner:

1. Click **Download Sample Format** to get a template
2. Fill in your company details (name, founder, website, pitch, pricing, etc.)
3. Upload the filled file — Claude will auto-extract all fields
4. Review the extracted fields and click **Save Configuration**

Your company name, founder details, and pitch are now used in all generated emails.

---

## Running the Pipeline

### Full pipeline (scrape → enrich → draft)

```bash
python run.py
```

### Individual stages

```bash
python run.py --scrape      # Scrape LinkedIn only
python run.py --enrich      # Enrich scraped leads
python run.py --draft       # Draft emails for enriched leads
```

Then open the dashboard to review and send emails.

---

## Pipeline Overview

```
LinkedIn Job Postings
  → scraper.py        (scrape AI/ML job postings)
  → enricher.py       (find company website + decision-maker email)
  → draft_emails.py   (Claude drafts personalized cold emails)
  → server.py         (dashboard: review, send, track)
  → email_sender.py   (SMTP send with open-tracking pixel)
  → reply_tracker.py  (IMAP poller, marks replied leads)
```

---

## Configuration Reference

| Where | What |
|-------|------|
| `.env` | API keys, SMTP/IMAP, LinkedIn credentials |
| Dashboard → Setup | Company name, founder, website, pitch, pricing |
| `company_brief.example.txt` | Sample format for the Setup upload |

Search queries, locations, and target decision-maker titles are auto-configured from your company profile. You can also override them in `.env`:

```env
SEARCH_QUERIES=AI Engineer|ML Engineer|LLM Engineer
SEARCH_LOCATIONS=United States|United Kingdom|Germany
TARGET_TITLES=CTO|CEO|Founder|VP of Engineering
```

---

## Email Open Tracking — Hosting Required

Open tracking works by embedding an invisible 1×1 pixel image in each sent email. When the recipient opens the email, their email client loads the image from your server — that load registers as an "open."

**This only works if your server is publicly accessible on the internet.** When running locally (`localhost:5000`), the tracking pixel URL is not reachable from outside your machine, so opens will not be recorded.

To enable tracking, deploy the server to a public host and set `BASE_URL` in your `.env`:

```env
BASE_URL=https://your-domain.com   # or your Railway / Render / VPS URL
```

**Free hosting options:**

| Platform | Notes |
|----------|-------|
| [Railway](https://railway.app) | Free tier, `Procfile` already included — deploy in 2 minutes |
| [Render](https://render.com) | Free tier, add a `render.yaml` |
| Any VPS | DigitalOcean, Hetzner, etc. — run `python server.py` behind nginx |

> **Reply tracking** (IMAP polling) works locally with no hosting needed — it connects outbound to your Gmail inbox and does not require a public URL.

---

## Security Notes

- Never commit `.env`, `company_config.json`, or `leads.db` — all are gitignored
- Use a dedicated LinkedIn account, not your personal one
- Gmail App Passwords are account-specific and can be revoked at any time

---

## Free API Keys

| Service | Free Tier | Link |
|---------|-----------|------|
| Anthropic | $5 credit | [console.anthropic.com](https://console.anthropic.com) |
| Groq | Generous free tier | [console.groq.com](https://console.groq.com) |
| Gemini | Free | [aistudio.google.com](https://aistudio.google.com) |
| Cerebras | 1M tokens/day | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| Hunter.io | 25 credits/month | [hunter.io](https://hunter.io) |
