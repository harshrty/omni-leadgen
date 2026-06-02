# How I Built an AI Agent That Finds B2B Leads, Writes Personalized Cold Emails, and Tracks Every Reply — For $0.002 Per Lead

**Author:** Harsh Singh
**GitHub:** [github.com/harshrty/omni-leadgen](https://github.com/harshrty/omni-leadgen)
**Category:** AI Automation · Sales Engineering · Open Source

---

## Executive Summary

Most B2B sales teams spend thousands of dollars every month on lead generation tools that deliver lists of names, not outcomes. They pay for Apollo.io to find contacts, pay again for a copywriting tool to write the email, pay again for an email tracker to know if it was opened, and still end up sending the same generic template to 500 people.

I built something different.

**omni-leadgen** is a fully autonomous AI agent that:

1. Watches LinkedIn for companies actively hiring AI engineers — a real-time buying signal
2. Finds the right decision maker at each company and locates their email address
3. Reads their actual job description and writes a unique, 500-word personalized email about it
4. Sends that email from your own Gmail account, at human-like speed
5. Tracks when the email is opened and when someone replies
6. Notifies you on Slack the moment a reply lands

The entire pipeline runs on your own machine. It costs roughly **$0.002 per email** in API fees. There is no subscription. No vendor. No lock-in. The code is open source and free.

In its first production run, it processed **2,214 scraped companies**, enriched **1,433 of them** with verified decision-maker contacts, and drafted personalized outreach emails for every single one — automatically.

---

## Part 1: The Problem

### What B2B Sales Outreach Actually Looks Like in 2025

If you sell a B2B service — consulting, software, AI development, design, anything — cold email is still one of the most effective ways to reach new clients. The math is simple: send 1,000 well-targeted, personalized emails, get a 2% reply rate, and that's 20 conversations. If 10% of those convert, that's 2 new clients from one automated pipeline.

But the execution is brutally expensive.

Here is what a typical sales stack costs per month:

| Tool | Purpose | Monthly Cost |
|------|---------|-------------|
| Apollo.io (Basic) | Lead database + emails | $49–$99 |
| Hunter.io (Starter) | Email verification | $49 |
| Instantly.ai | Email sending + tracking | $37–$97 |
| Copy.ai or Lavender | Email writing | $49–$99 |
| Clay.com | Lead enrichment | $149–$800 |
| **Total** | | **$333–$1,144/month** |

And after all that spending, what do you get? A list of leads. A template. A tool that sends the template to everyone. The email says *"Hi [First Name], I came across your company and thought you might be interested in…"* — and the prospect deletes it in three seconds.

The fundamental problem is not the tools. The problem is the approach.

**Generic outreach fails because it treats every prospect the same.**

A CTO at a 500-person logistics company has completely different problems than a VP of Engineering at a 50-person SaaS startup. They are both "decision makers." They are both "in tech." But the email that resonates with one will be completely irrelevant to the other. No template can fix this. Only real personalization can. And real personalization, at scale, requires AI.

---

## Part 2: The Insight That Changed Everything

### Why Job Postings Are the Best Buying Signal in B2B Sales

Most lead generation tools start with a static database. They ask: *"What type of company do you want to reach?"* You pick an industry, a company size, a geography, and you get a list. The problem is that every other sales team using that tool gets the same list. You are all competing for the same inboxes.

I started thinking about this differently.

**What if, instead of starting with who the company is, you started with what the company is actively doing right now?**

Specifically: when a company posts a job opening for an AI Engineer or Machine Learning Engineer, it is sending a very clear signal to the world. It is saying:

- *"We have committed budget to an AI initiative."*
- *"We have a problem we want to solve with AI."*
- *"We are struggling to find or afford in-house talent to solve it."*
- *"We are under pressure — from leadership, from competition, from the board — to show AI results."*

This is not a passive lead. This is a prospect in active pain.

If your company sells AI services, AI development, AI consulting, or AI staffing, you could not ask for a warmer signal than this. The company has already decided to invest in AI. They have already decided they need help. The only question is whether they hire someone full-time (slow, expensive, uncertain) or work with an implementation partner (fast, accountable, results-focused).

**This was the core hypothesis behind omni-leadgen:**

> Companies actively hiring AI talent are the highest-intent B2B prospects for AI service providers. Finding them in real time, at scale, and reaching the right decision maker with a relevant, personalized message — before a competitor does — is the entire strategy.

---

## Part 3: How the Agent Works

### A Complete Walk-Through of Every Stage

Think of omni-leadgen as a five-stage autonomous pipeline. Each stage feeds the next, and the whole system runs with minimal human intervention. Here is exactly what happens, in plain language.

---

### Stage 1: The Scout — Watching LinkedIn for Buying Signals

**What it does:** Monitors LinkedIn for companies hiring AI and machine learning engineers, in real time.

**How it works:**

Every time you run the pipeline, the agent opens a web browser in the background (invisible, headless) and logs into LinkedIn using a dedicated account. It then searches for job postings using 12 different search queries across 17 countries:

- "AI Engineer", "Machine Learning Engineer", "LLM Engineer"
- "GenAI Developer", "MLOps Engineer", "Deep Learning Engineer"
- "NLP Engineer", "Computer Vision Engineer", "AI Research Engineer"
- Across the USA, UK, Germany, France, Netherlands, Ireland, Switzerland, Sweden, and 9 more countries

For each search result, the agent reads the job posting and asks: *"Is this a real AI role or just a generic software engineering job that happens to mention AI?"* It filters out Java developers, basic IT roles, and anything that does not match genuine AI/ML work. Only the relevant ones pass through.

It then visits each job posting individually to read the full job description — the specific technologies mentioned (PyTorch, LangChain, RAG pipelines, LLM fine-tuning), the company context, the role requirements. This full description is stored for later use in email generation.

**The result:** A database of companies actively hiring AI talent, with their job descriptions, locations, posting dates, and salary ranges — updated every 72 hours.

**In plain English:** The agent is doing what a human research assistant would do if you asked them to *"check LinkedIn every morning and find every company in the US and Europe that just posted an AI job."* Except the agent does it in minutes, not hours, and covers 17 countries simultaneously.

---

### Stage 2: The Detective — Finding the Right Person's Email

**What it does:** For each company found in Stage 1, finds the name and email address of the decision maker most likely to care about AI services — the CTO, CEO, VP of Engineering, Head of AI, or similar.

**How it works:**

This is the hardest part of any lead generation process. A company might have 500 employees, but you only want to email one specific person. Getting that wrong means your perfectly crafted email lands in the wrong inbox and gets ignored or marked as spam.

The agent uses a four-layer approach, trying each method in sequence until it finds a verified email:

**Layer 1 — Hunter.io API**

Hunter.io is a professional tool that has indexed millions of corporate email addresses from public sources on the web. The agent sends the company's domain name to Hunter.io and asks: *"Who works at this company and what is their email?"* Hunter returns a list, and the agent picks the most senior person from the "executive" category — typically the CTO, CEO, or VP.

The agent supports up to 20 Hunter.io API keys simultaneously. Each account gets 25 free credits per month. With 20 accounts, that is 500 free contacts found before any cost is incurred.

**Layer 2 — Email Pattern Guessing + SMTP Verification**

If Hunter does not have a record for a company, the agent switches to a technique called email pattern guessing. Here is how it works:

Almost every company uses one of these email formats for their employees:

```
john.smith@company.com
jsmith@company.com
john@company.com
johnsmith@company.com
smith.john@company.com
john_smith@company.com
j.smith@company.com
johns@company.com
```

The agent generates all 8 possible pattern variations for the decision maker's name, then — crucially — it does not just guess. It **verifies each guess** by making a silent SMTP connection to the company's mail server and asking: *"Does this email address exist?"* without actually sending an email. This is called an SMTP RCPT-TO check, and it works like ringing someone's doorbell to see if they are home without leaving a note.

If the mail server confirms the address exists (returns code 250), the agent marks it as "verified" and moves on. If the server will not confirm or deny (a "catch-all" domain), the agent uses the first pattern as a best guess.

**Layer 3 — AI-Powered Decision Maker Extraction**

Sometimes the company website has the team's names listed on an "About" page or in press releases. The agent scrapes the company website, extracts all the text, and sends it to an LLM (Groq's Llama 3.3-70b model) with the instruction: *"Read this text and identify who the CTO, CEO, VP of Engineering, or Head of AI is."* The LLM reads the page and returns a structured answer with the person's name and title.

**Layer 4 — DuckDuckGo Domain Discovery**

Before any of the above can run, the agent needs to know the company's website domain. It searches DuckDuckGo for *"[Company Name] official website"*, filters out aggregators and job boards, and extracts the real company domain. This step has its own retry logic with exponential backoff in case of network issues.

**The result:** A verified email address, name, and title for the most senior AI decision maker at each company. The current enrichment rate is approximately 64.7% — meaning for every 10 companies found, 6–7 come back with a verified contact.

**In plain English:** Finding someone's work email used to require either paying a lot of money for a database tool or spending 10 minutes manually searching on LinkedIn, Google, and the company website for each contact. The agent does this for hundreds of companies at once, in parallel, using 4 simultaneous workers — roughly 4 times faster than doing it one at a time.

---

### Stage 3: The Copywriter — Writing a Unique Email for Every Single Lead

**What it does:** Reads the actual job description for each company and writes a personalized, 500-word cold email that sounds like a human senior executive wrote it specifically for that company.

**How it works:**

For each lead, the agent sends the following information to Claude (Anthropic's AI model):

- The company's name, industry, and what they do
- The job title they are hiring for
- The full job description text (up to 800 characters of the most relevant section)
- The decision maker's name and title
- Your company's full profile (services, value proposition, pricing, case studies, ROI statistics)

It then gives Claude a very specific set of instructions: write a 480–560 word formal cold email that follows this exact 9-section structure:

| Section | Content |
|---------|---------|
| **1. Opening** | Introduce yourself and connect your reach-out to their specific job posting |
| **2. The AI ROI Crisis Hook** | Reference industry-wide statistics about AI project failure rates |
| **3. Company Positioning** | Explain what your company does and why you are different |
| **4. "Why This Matters to [Company]"** | Custom section referencing technologies from their actual JD |
| **5. The 90-Day Blueprint** | Your engagement phases, with real pricing and timelines |
| **6. Partnership Value** | What makes you different from consultants and staffing agencies |
| **7. Industry Context** | Show you understand their specific business and operational pressures |
| **8. Soft CTA** | Ask for 20 minutes, not a commitment |
| **9. Closing** | Professional sign-off with contact information |

The email is required to reference technologies that actually appear in their job description. If they are hiring an engineer who knows LangChain and AWS, the email mentions LangChain and AWS. If they are hiring for a computer vision role in a healthcare company, the email connects computer vision to healthcare-specific outcomes. This cannot be faked with a template.

The drafting stage runs 5 simultaneous Claude workers, with a 3-attempt retry on any malformed or empty response.

**The result:** A unique, professional, ~500-word email for every company in the database — drafted in parallel, at a cost of approximately $0.002 each.

**In plain English:** A skilled human copywriter who writes personalized cold emails charges $50–$200 per email. A good sales development representative (SDR) who researches prospects and personalizes outreach can produce maybe 10–15 emails per day. The agent produces personalized emails for hundreds of companies simultaneously, and because it reads the actual job description, no two emails are the same.

---

### Stage 4: The Sender — Delivering Emails Like a Human

**What it does:** Sends approved emails from your Gmail account, at human-like timing, with full open-tracking embedded.

**How it works:**

You review every email in the web dashboard before it sends. The dashboard shows the company name, the decision maker's name and email, and the full draft. You can edit any field before sending.

When you trigger bulk send, the agent does not blast out 200 emails in 10 seconds the way a spam tool would. It waits a random amount of time between each email — between 45 and 90 seconds — because human beings do not send emails at machine-gun pace. This randomness is important: email servers look for robotic patterns and will flag or block accounts that send at inhuman speed.

Each email is built with two parts inside it:

1. **Plain text version** — what the recipient reads
2. **Ghost HTML version** — identical content, but with an invisible 1-pixel image embedded

The invisible pixel is hosted on your server. When a recipient opens the email in an HTML-capable client (Gmail, Outlook, Apple Mail), their client automatically loads that tiny image from your server. That load registers as an "open" in your database, timestamped to the second.

The system also saves a unique Message-ID for every email sent. This is a technical identifier embedded in the email headers. When someone replies to your email, their reply automatically contains this ID in its headers — email clients do this automatically as part of the threading protocol.

**The result:** Emails are sent, opens are tracked, replies are attributed — all automatically, with no manual effort.

---

### Stage 5: The Closer — What Happens After Someone Replies

**What it does:** Detects replies, notifies you instantly, manages follow-up schedules, and keeps your pipeline organized.

**How it works:**

A background thread polls your email inbox every 5 minutes using IMAP (the standard protocol for reading emails). It scans for new messages and uses two strategies to match replies back to leads:

- **Primary:** Matches the `In-Reply-To` or `References` header in the reply to the stored Message-ID
- **Fallback:** Matches the sender's email address to the decision maker email on record (used when the reply comes from a different email client that strips headers)

The moment a reply is detected, three things happen simultaneously:

1. The lead's status in the database updates from "sent" to "replied"
2. The follow-up schedule for that lead is cleared automatically
3. A Slack notification fires: *"Reply received from Jane Smith at Acme Corp!"*

For leads that do not reply, the system automatically schedules a follow-up 3 days after the initial send. The dashboard has a "Due for Follow-Up" filter to show exactly who needs a nudge.

**In plain English:** You send the emails and forget about it. The agent watches your inbox. The moment someone responds, your phone buzzes. You never miss a reply, and you never have to manually check who got back to you.

---

## Part 4: The Technical Architecture

### How It Is Actually Built

| Component | Technology |
|-----------|-----------|
| Language | Python 3.10+ |
| Web Framework | Flask |
| Database | SQLite (local, no cloud required) |
| LinkedIn Scraping | Playwright (headless Chromium) + Scrapling fallback |
| Email Discovery | Hunter.io API (up to 20 key rotation) |
| Email Verification | SMTP RCPT-TO + DNS MX lookup |
| Decision Maker Extraction | Groq Llama 3.3-70b |
| Email Generation | Claude Haiku (claude-haiku-4-5) |
| Email Sending | Gmail SMTP (STARTTLS, port 587) |
| Open Tracking | 1×1 GIF served by Flask at `/api/track/open/<id>` |
| Reply Tracking | IMAP4_SSL polling (every 300 seconds) |
| Enricher Parallelism | `ThreadPoolExecutor(max_workers=4)` |
| Drafter Parallelism | `ThreadPoolExecutor(max_workers=5)` |
| Thread Safety | `threading.Lock()` on HunterRotator |
| Notifications | Slack Incoming Webhook |
| Configuration | AI-extracted `company_config.json` via dashboard |

### AI Provider Fallback Chain

The pipeline uses a priority-ordered fallback chain so it never stops due to a single provider's rate limits:

```
Groq (llama-3.3-70b) → Cerebras → SambaNova → Together AI → Claude Haiku
```

Every provider in this chain has a free tier. The pipeline can run entirely for free until volume demands paid tiers.

### Database Schema

The `leads` table has 30 columns tracking the full lifecycle of every lead:

```
Core:         company_name, company_website, company_domain, company_description,
              company_industry, company_size
Job:          job_title, job_description, job_url, job_location,
              job_posted_date, salary, tech_keywords
Contact:      decision_maker_name, decision_maker_title,
              decision_maker_email, decision_maker_linkedin
Draft:        draft_subject, draft_email, draft_linkedin_note
Tracking:     status, message_id, sent_at, opened_at, replied_at,
              follow_up_at, created_at, updated_at
```

Status values follow the pipeline: `scraped → enriched → drafted → sent → opened → replied`

### Anti-Detection Measures

LinkedIn actively blocks scrapers. The following measures are in place:

- Custom Chrome 122 user agent
- Realistic viewport (1366×768), locale (en-US), timezone (America/New_York)
- `--disable-blink-features=AutomationControlled` flag
- Random delays: 2–5 seconds between page requests, 3–7 seconds between search combinations
- Images, fonts, and videos blocked (faster, less traceable)
- Browser session reused for 12 hours (fewer logins = less suspicious)
- Session state saved to `linkedin_state.json`

---

## Part 5: Performance & Results

### Real Numbers From Production

| Metric | Value |
|--------|-------|
| Total companies scraped | 2,214 |
| Successfully enriched (email found) | 1,433 |
| Enrichment success rate | 64.7% |
| Emails tracked as opened | 1 (100% open rate on test send) |
| Cost per email drafted | ~$0.002 (Claude Haiku) |
| Cost per contact found | $0 (Hunter free tier, 25 credits/key) |
| Enricher throughput (parallel) | ~4× faster than sequential |
| Drafter throughput (parallel) | ~5× faster than sequential |
| Description fetch limit | 150 per run (env-configurable) |

### Economics at Scale

| Monthly Volume | Claude API | Hunter.io | Total Cost | vs. SaaS Stack |
|---------------|-----------|-----------|------------|----------------|
| 100 emails | $0.20 | $0 | **$0.20** | $333 savings |
| 500 emails | $1.00 | $0 | **$1.00** | $400+ savings |
| 2,000 emails | $4.00 | $49 | **$53** | $600+ savings |
| 5,000 emails | $10.00 | $99 | **$109** | $900+ savings |

---

## Part 6: What Makes It Different

### Why This Is Not Just Another Lead Gen Tool

**1. The signal is smarter.**
Most lead gen tools start with a static database of companies. omni-leadgen starts with live, real-time hiring activity. A company posting an AI job today is a warmer prospect than one that appeared in a database six months ago.

**2. The personalization is real.**
Every single email references the specific job description of the company being emailed. If they are hiring an engineer who knows RAG pipelines and LangGraph, the email mentions RAG pipelines and LangGraph. This is not a mail-merge. It is genuine contextual personalization generated fresh for each lead.

**3. It is yours.**
The code runs on your machine. Your leads stay in your database. Your emails come from your Gmail account. There is no third party storing your prospect data, your email content, or your sales strategy.

**4. It is free to run.**
Every API used has a free tier. You can run hundreds of enrichments and dozens of email drafts for essentially nothing during testing and early use. At scale, the cost is a fraction of any SaaS alternative.

**5. It configures itself.**
Upload your company profile document in the dashboard. Claude reads it and automatically extracts your company name, founder name, website, value proposition, pricing, ROI statistics, and contact information. No manual configuration. One upload, everything set.

**6. It is fully observable.**
Every lead, every status change, every email draft, every open, and every reply is visible in the web dashboard. You always know exactly what the pipeline has done and what it is waiting for.

---

## Part 7: Lessons Learned

### What Building This Taught Me

**Lesson 1: The data pipeline is harder than the AI part.**
It took far longer to reliably scrape LinkedIn, handle rate limits, parse inconsistent HTML structures, and validate email addresses than it did to write the AI email generation prompt. The AI part is 10% of the work. The plumbing is 90%. If you are building AI-powered tools, expect most of your engineering time to go into data collection and cleaning, not model calls.

**Lesson 2: Email deliverability is a science.**
Sending emails that actually reach inboxes — not spam folders — requires deliberate engineering. Multipart MIME structure with plain text as primary. Random delays between sends. Proper Message-ID headers. SPF and DKIM alignment on the sending domain. Missing any of these and your emails never get read, no matter how good they are.

**Lesson 3: Parallelism changes everything at the margins.**
The original sequential enricher took 150–300 seconds for 100 leads. After adding a ThreadPoolExecutor with 4 workers, the same job runs in 40–75 seconds. A 4× speedup with a 10-line change. Thread safety — especially for the API key rotator — required careful use of `threading.Lock()`. Concurrency bugs are silent and intermittent, which makes them particularly difficult to debug.

**Lesson 4: LLMs need structure, not freedom.**
The first version of the email prompt said "write a personalized cold email about [company]." The output was inconsistent, too short, and generic. The current version specifies 9 mandatory sections, a precise word count (480–560 words), forbidden punctuation (no em-dashes or en-dashes), required phrases for specific sections, and explicit instructions about what not to do. Constraint produces quality. The more specific your prompt, the more reliable the output.

**Lesson 5: The product is the pipeline, not the email.**
The most valuable thing about this system is not any single email. It is the fact that the entire process — from spotting a LinkedIn job posting to having a personalized email ready to send — takes minutes instead of days. That velocity is the competitive advantage. By the time a competitor's human SDR finishes researching the same lead, this pipeline has already sent the email.

**Lesson 6: Free API tiers are remarkably powerful.**
Groq (Llama 3.3-70b) is fast and free. Cerebras is free. SambaNova is free. Hunter.io gives 25 free credits per account and you can create multiple accounts. DuckDuckGo search is free. The entire enrichment pipeline can run at zero cost for small volumes. This changes the economics of building AI-powered tools dramatically — you can iterate and test without a credit card.

---

## Part 8: Future Roadmap

### What Is Coming Next

| Feature | Description | Status |
|---------|-------------|--------|
| Automatic follow-up sequences | 3-day follow-up emails, auto-drafted and auto-sent if no reply | Partially built (`follow_up_at` column exists) |
| Apollo.io integration | Additional lead source with richer company data and intent signals | Planned |
| Multi-provider email verification | Combining SMTP + Hunter + ZeroBounce for higher accuracy | Planned |
| A/B testing framework | Test different subject lines and email angles, track conversion by variant | Planned |
| Webhook triggers | Zapier/n8n integration to pipe replied leads directly into CRM | Planned |
| Multi-user support | Team accounts with shared lead pool but separate email sending | Planned |
| Docker deployment | One-command setup for non-technical users | Planned |
| Fine-tuned email model | Custom model trained on emails that generated real replies | Research |

---

## Part 9: How to Use It

### Getting Started in 10 Minutes

**Prerequisites:**
- Python 3.10+
- A Gmail account with App Password enabled
- A LinkedIn account (dedicated/throwaway recommended)
- An Anthropic API key (for email drafting — $5 free credit on signup)

**Setup:**

```bash
# 1. Clone the repository
git clone https://github.com/harshrty/omni-leadgen
cd omni-leadgen

# 2. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 3. Configure credentials
cp .env.example .env
# Edit .env and add your API keys and email credentials

# 4. Start the dashboard
python server.py
```

**First run:**
1. Open `http://localhost:5000` in your browser
2. Click **⚙ Setup** and upload your company profile document (use the sample format as a guide)
3. Claude will automatically extract your company name, founder details, pitch, and pricing
4. Review the extracted fields and click **Save Configuration**
5. Run the scraper: `python scraper.py`
6. Run the enricher: `python enricher.py`
7. Run the drafter: `python draft_emails.py`
8. Review emails in the dashboard and click **Bulk Send**

**Minimum required API keys:**
- `ANTHROPIC_API_KEY` — for email drafting (~$0.002/email)
- `SMTP_USER` + `SMTP_PASS` — your Gmail + App Password (for sending)
- `IMAP_USER` + `IMAP_PASS` — same Gmail (for reply tracking)
- `LINKEDIN_EMAIL` + `LINKEDIN_PASS` — for scraping

Everything else (Groq, Hunter, Cerebras, Slack) is optional and enhances the pipeline.

---

## Conclusion

omni-leadgen is proof that a single developer, with access to the right AI APIs, can build a tool that competes with — and in many ways surpasses — an entire SaaS product category that charges hundreds of dollars per month.

The system processes buying signals in real time. It finds the right person. It writes a genuinely personalized email. It sends it, tracks it, and notifies you when someone responds. It does all of this for fractions of a cent per lead.

If you sell B2B services — particularly in AI, technology consulting, development, or any space where your buyers are enterprise companies with technical leadership — this is a pipeline worth running.

The code is open source. Clone it, configure it with your own company profile, and run it.

---

**Repository:** [github.com/harshrty/omni-leadgen](https://github.com/harshrty/omni-leadgen)
**Tech Stack:** Python · Flask · Claude (Anthropic) · Groq · Playwright · Scrapling · SQLite · Hunter.io · Gmail SMTP/IMAP
**License:** Open Source

---

*Built by Harsh Singh — if this saves you money or time, star the repo and share it with someone who needs it.*
