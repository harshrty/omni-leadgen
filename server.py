"""
Omnithrive Dashboard Server.

Endpoints:
  GET  /                          → Dashboard UI
  GET  /api/leads                 → All leads as JSON
  GET  /api/stats                 → Aggregate pipeline stats
  POST /api/leads/<id>/send       → Send email for a lead
  GET  /api/track/open/<lead_id>  → 1x1 transparent pixel + mark lead as Opened

Start: python server.py
"""
import base64
import logging
import random
import sys as _sys
import threading
import time as _time

from flask import Flask, jsonify, request, send_from_directory

from config import SERVER_HOST, SERVER_PORT, ANTHROPIC_API_KEY
from db import get_all_leads, get_lead_by_id, mark_opened, update_lead, clone_lead, delete_lead
from email_sender import send_email
from reply_tracker import start_background_thread

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")
if hasattr(_sys.stderr, "reconfigure"):
    _sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bulk Send State
# ---------------------------------------------------------------------------
_bulk_state = {
    "running": False, "total": 0, "sent": 0, "failed": 0,
    "current": "", "done": False, "stop_requested": False, "errors": [],
}
_bulk_lock = threading.Lock()


def _bulk_send_worker(lead_ids, delay_min, delay_max, daily_cap):
    global _bulk_state
    sent = 0
    failed = 0

    for i, lead_id in enumerate(lead_ids):
        with _bulk_lock:
            if _bulk_state["stop_requested"]:
                break
        if sent >= daily_cap:
            break

        lead = get_lead_by_id(lead_id)
        if not lead:
            continue

        # Skip if already sent (e.g. sent individually while bulk was running)
        if lead.get("status") in ("sent", "opened", "replied"):
            with _bulk_lock:
                _bulk_state["total"] = max(0, _bulk_state["total"] - 1)
            continue

        company = lead.get("company_name", "")
        with _bulk_lock:
            _bulk_state["current"] = "Sending to " + company + "..."

        try:
            send_email(lead)
            sent += 1
            with _bulk_lock:
                _bulk_state["sent"] = sent
            logger.info("Bulk send: sent lead_id=%d company=%s", lead_id, company)
        except Exception as e:
            failed += 1
            with _bulk_lock:
                _bulk_state["failed"] = failed
                _bulk_state["errors"].append(company + ": " + str(e)[:60])
            logger.error("Bulk send error lead_id=%d: %s", lead_id, e)

        # Human-like delay between sends (skip after last)
        if i < len(lead_ids) - 1:
            with _bulk_lock:
                stop = _bulk_state["stop_requested"]
            if stop:
                break
            delay = random.randint(delay_min, delay_max)
            with _bulk_lock:
                _bulk_state["current"] = "Waiting " + str(delay) + "s before next..."
            _time.sleep(delay)

    with _bulk_lock:
        _bulk_state["running"] = False
        _bulk_state["done"] = True
        _bulk_state["current"] = ""

app = Flask(__name__, static_folder="static", template_folder="templates")

# 1x1 transparent GIF
_PIXEL_B64 = (
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)
PIXEL_BYTES = base64.b64decode(_PIXEL_B64)


# ---------------------------------------------------------------------------
# Dashboard UI
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    return send_from_directory("templates", "dashboard.html")


# ---------------------------------------------------------------------------
# API: Leads & Stats
# ---------------------------------------------------------------------------

@app.route("/api/leads")
def api_leads():
    leads = get_all_leads()
    safe = []
    for lead in leads:
        # Hide leads with no email address — they can never be sent
        if not (lead.get("decision_maker_email") or "").strip():
            continue
        safe.append({
            "id": lead["id"],
            "company_name": lead.get("company_name") or "",
            "job_title": lead.get("job_title") or "",
            "job_description": (lead.get("job_description") or "")[:200],
            "tech_keywords": lead.get("tech_keywords") or "",
            "draft_subject": lead.get("draft_subject") or "",
            "draft_email": lead.get("draft_email") or "",
            "company_industry": lead.get("company_industry") or "",
            "company_description": lead.get("company_description") or "",
            "company_size": lead.get("company_size") or "",
            "decision_maker_name": lead.get("decision_maker_name") or "",
            "decision_maker_title": lead.get("decision_maker_title") or "",
            "decision_maker_email": lead.get("decision_maker_email") or "",
            "status": lead.get("status") or "scraped",
            "sent_at": lead.get("sent_at") or "",
            "opened_at": lead.get("opened_at") or "",
            "replied_at": lead.get("replied_at") or "",
            "created_at": lead.get("created_at") or "",
        })
    return jsonify(safe)


@app.route("/api/stats")
def api_stats():
    leads = get_all_leads()
    stats = {
        "total_scraped": 0,
        "total_enriched": 0,
        "total_sent": 0,
        "total_opened": 0,
        "total_replied": 0,
        "no_reply": 0,
    }
    for lead in leads:
        status = (lead.get("status") or "scraped").lower()
        stats["total_scraped"] += 1
        if status in ("enriched", "drafted", "sent", "opened", "replied"):
            stats["total_enriched"] += 1
        if status in ("sent", "opened", "replied"):
            stats["total_sent"] += 1
        if status in ("opened", "replied"):
            stats["total_opened"] += 1
        if status == "replied":
            stats["total_replied"] += 1
    # No reply = sent or opened but not replied
    stats["no_reply"] = stats["total_sent"] - stats["total_replied"]
    return jsonify(stats)


# ---------------------------------------------------------------------------
# API: Send Email
# ---------------------------------------------------------------------------

@app.route("/api/leads/<int:lead_id>/send", methods=["POST"])
def api_send(lead_id):
    lead = get_lead_by_id(lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404

    if lead.get("status") in ("sent", "opened", "replied"):
        return jsonify({"error": "Email already sent for this lead"}), 400

    if not (lead.get("draft_email") or "").strip():
        return jsonify({"error": "No drafted email for this lead"}), 400

    if not (lead.get("decision_maker_email") or "").strip():
        return jsonify({"error": "No recipient email address for this lead"}), 400

    try:
        message_id = send_email(lead)
        logger.info("Email sent: lead_id=%d message_id=%s", lead_id, message_id)
        return jsonify({"ok": True, "message_id": message_id})
    except Exception as e:
        logger.error("Send failed for lead_id=%d: %s", lead_id, e)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# API: Edit Lead
# ---------------------------------------------------------------------------

@app.route("/api/leads/<int:lead_id>/update", methods=["POST"])
def api_update_lead(lead_id):
    lead = get_lead_by_id(lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404

    data = request.get_json(silent=True) or {}
    allowed = ["decision_maker_name", "decision_maker_title", "decision_maker_email",
               "company_description", "company_industry", "tech_keywords"]
    fields = {k: v for k, v in data.items() if k in allowed and v is not None}

    if not fields:
        return jsonify({"error": "No valid fields to update"}), 400

    update_lead(lead_id, **fields)
    return jsonify({"ok": True})


@app.route("/api/leads/<int:lead_id>/redraft", methods=["POST"])
def api_redraft(lead_id):
    lead = get_lead_by_id(lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404

    if lead.get("status") in ("sent", "opened", "replied"):
        return jsonify({"error": "Cannot redraft an already-sent lead"}), 400

    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    try:
        import anthropic
        from draft_emails import generate_email
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        subject, body = generate_email(client, lead)
        if not subject or not body:
            return jsonify({"error": "AI returned empty draft"}), 500

        update_lead(lead_id, draft_subject=subject, draft_email=body, status="drafted")
        logger.info("Redrafted lead_id=%d", lead_id)
        return jsonify({"ok": True, "draft_subject": subject, "draft_email": body})
    except Exception as e:
        logger.error("Redraft failed for lead_id=%d: %s", lead_id, e)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# API: Classify Company Sizes (AI background task)
# ---------------------------------------------------------------------------

_classify_state = {"running": False, "done": 0, "total": 0, "errors": 0, "finished": False}
_classify_lock = threading.Lock()


def _classify_worker():
    global _classify_state
    from config import ANTHROPIC_API_KEY as _ak
    import anthropic

    leads = get_all_leads()
    unclassified = [l for l in leads if not (l.get("company_size") or "").strip()]

    with _classify_lock:
        _classify_state.update({"total": len(unclassified), "done": 0, "errors": 0, "finished": False})

    if not unclassified:
        with _classify_lock:
            _classify_state.update({"running": False, "finished": True})
        return

    client = anthropic.Anthropic(api_key=_ak)

    for lead in unclassified:
        try:
            prompt = (
                "Classify this company's size. Reply with EXACTLY one word: small, mid, or large.\n"
                "- small: startup or fewer than 200 employees\n"
                "- mid: 200 to 2000 employees, scale-up, series B/C\n"
                "- large: over 2000 employees, enterprise, publicly traded\n\n"
                f"Company: {lead.get('company_name','')}\n"
                f"Industry: {lead.get('company_industry','')}\n"
                f"Description: {(lead.get('company_description') or '')[:300]}\n"
                f"Hiring for: {lead.get('job_title','')}\n"
                f"JD excerpt: {(lead.get('job_description') or '')[:200]}\n\n"
                "One word only:"
            )
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=5,
                messages=[{"role": "user", "content": prompt}],
            )
            parts = msg.content[0].text.strip().lower().split()
            size = parts[0] if parts else "unknown"
            if size not in ("small", "mid", "large"):
                size = "unknown"
            update_lead(lead["id"], company_size=size)
            with _classify_lock:
                _classify_state["done"] += 1
        except Exception as e:
            logger.error("Classify error lead_id=%d: %s", lead["id"], e)
            with _classify_lock:
                _classify_state["errors"] += 1
        _time.sleep(0.3)

    with _classify_lock:
        _classify_state.update({"running": False, "finished": True})
    logger.info("Company size classification done.")


@app.route("/api/classify-sizes/start", methods=["POST"])
def api_classify_start():
    with _classify_lock:
        if _classify_state["running"]:
            return jsonify({"error": "Already running"}), 400
        if not ANTHROPIC_API_KEY:
            return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 500
        _classify_state["running"] = True
        _classify_state["finished"] = False

    t = threading.Thread(target=_classify_worker, daemon=True, name="Classifier")
    t.start()
    logger.info("Company size classification started.")
    return jsonify({"ok": True})


@app.route("/api/classify-sizes/status")
def api_classify_status():
    with _classify_lock:
        return jsonify(dict(_classify_state))


# ---------------------------------------------------------------------------
# API: Clone Lead (add 2nd decision maker)
# ---------------------------------------------------------------------------

@app.route("/api/leads/<int:lead_id>/delete", methods=["POST"])
def api_delete_lead(lead_id):
    lead = get_lead_by_id(lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    delete_lead(lead_id)
    logger.info("Deleted lead_id=%d", lead_id)
    return jsonify({"ok": True})


@app.route("/api/leads/<int:lead_id>/clone", methods=["POST"])
def api_clone_lead(lead_id):
    lead = get_lead_by_id(lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404

    data = request.get_json(silent=True) or {}
    dm_name  = (data.get("dm_name")  or "").strip()
    dm_title = (data.get("dm_title") or "").strip()
    dm_email = (data.get("dm_email") or "").strip()

    if not dm_email:
        return jsonify({"error": "DM email is required"}), 400

    new_id = clone_lead(lead_id, dm_name, dm_title, dm_email)
    if not new_id:
        return jsonify({"error": "Failed to clone lead"}), 500

    # Auto-draft immediately if we have a name and API key
    if ANTHROPIC_API_KEY and dm_name:
        try:
            import anthropic
            from draft_emails import generate_email
            new_lead = get_lead_by_id(new_id)
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            subject, body = generate_email(client, new_lead)
            if subject and body:
                update_lead(new_id, draft_subject=subject, draft_email=body, status="drafted")
                logger.info("Cloned+drafted lead_id=%d from lead_id=%d", new_id, lead_id)
        except Exception as e:
            logger.error("Auto-draft failed for cloned lead_id=%d: %s", new_id, e)

    return jsonify({"ok": True, "new_id": new_id})


# ---------------------------------------------------------------------------
# Tracking: Open Pixel
# ---------------------------------------------------------------------------

@app.route("/api/track/open/<int:lead_id>")
def track_open(lead_id):
    try:
        mark_opened(lead_id)
        logger.info("Open tracked: lead_id=%d ip=%s", lead_id, request.remote_addr)
    except Exception as e:
        logger.error("Open tracking error for lead_id=%d: %s", lead_id, e)

    from flask import Response
    return Response(
        PIXEL_BYTES,
        status=200,
        mimetype="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


# ---------------------------------------------------------------------------
# API: Bulk Send
# ---------------------------------------------------------------------------

@app.route("/api/bulk-send/start", methods=["POST"])
def api_bulk_start():
    global _bulk_state
    with _bulk_lock:
        if _bulk_state["running"]:
            return jsonify({"error": "Bulk send already running"}), 400

    data = request.get_json(silent=True) or {}
    delay_min = max(30, int(data.get("delay_min", 45)))
    delay_max = max(delay_min + 10, int(data.get("delay_max", 90)))
    daily_cap = min(100, max(1, int(data.get("daily_cap", 50))))

    leads = get_all_leads()
    drafted_all = [
        l for l in leads
        if l.get("status") == "drafted"
        and (l.get("decision_maker_email") or "").strip()
        and (l.get("draft_email") or "").strip()
    ]
    # Deduplicate by email — keep only the first lead per email address
    seen_emails = set()
    drafted = []
    for l in drafted_all:
        email = (l.get("decision_maker_email") or "").strip().lower()
        if email not in seen_emails:
            seen_emails.add(email)
            drafted.append(l)

    if not drafted:
        return jsonify({"error": "No drafted leads ready to send"}), 400

    lead_ids = [l["id"] for l in drafted]
    cap = min(len(lead_ids), daily_cap)

    with _bulk_lock:
        _bulk_state.update({
            "running": True, "total": cap, "sent": 0, "failed": 0,
            "current": "Starting...", "done": False,
            "stop_requested": False, "errors": [],
        })

    t = threading.Thread(
        target=_bulk_send_worker,
        args=(lead_ids, delay_min, delay_max, daily_cap),
        daemon=True, name="BulkSender",
    )
    t.start()
    logger.info("Bulk send started: %d leads, delay=%d-%ds, cap=%d", cap, delay_min, delay_max, daily_cap)
    return jsonify({"ok": True, "total": cap})


@app.route("/api/bulk-send/status")
def api_bulk_status():
    with _bulk_lock:
        return jsonify(dict(_bulk_state))


@app.route("/api/bulk-send/stop", methods=["POST"])
def api_bulk_stop():
    with _bulk_lock:
        _bulk_state["stop_requested"] = True
    logger.info("Bulk send stop requested.")
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API: Company Config (Setup tab)
# ---------------------------------------------------------------------------

def _apply_config_to_runtime(cc: dict):
    """Hot-reload extracted config into running modules without a server restart."""
    import config as _cfg
    import draft_emails as _de

    _cfg.COMPANY_NAME    = cc.get("company_name",    "") or _cfg.COMPANY_NAME
    _cfg.FOUNDER_NAME    = cc.get("founder_name",    "") or _cfg.FOUNDER_NAME
    _cfg.FOUNDER_TITLE   = cc.get("founder_title",   "Founder & CEO")
    _cfg.COMPANY_WEBSITE = cc.get("company_website", "")
    _cfg.COMPANY_PITCH   = cc.get("company_pitch",   "")
    _cfg.CALENDAR_URL    = cc.get("calendar_url",    "")
    if cc.get("search_queries"):
        _cfg.SEARCH_QUERIES   = cc["search_queries"]
    if cc.get("search_locations"):
        _cfg.SEARCH_LOCATIONS = cc["search_locations"]
    if cc.get("target_titles"):
        _cfg.TARGET_TITLES    = cc["target_titles"]

    # Rebuild the context string draft_emails injects into prompts
    _de.OMNITHRIVE_CONTEXT = _de.load_company_context()


@app.route("/api/config/upload", methods=["POST"])
def api_config_upload():
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY not set — required to parse the context file"}), 500

    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file uploaded (field name must be 'file')"}), 400

    filename = f.filename or "upload.txt"
    try:
        from company_config import extract_text_from_file, parse_company_context, save_config
        file_bytes = f.read()
        text = extract_text_from_file(file_bytes, filename)
        if not text.strip():
            return jsonify({"error": "Uploaded file is empty"}), 400

        cc = parse_company_context(text, ANTHROPIC_API_KEY)
        save_config(cc)
        _apply_config_to_runtime(cc)
        logger.info("Company config updated via upload: company=%s founder=%s",
                    cc.get("company_name"), cc.get("founder_name"))
        return jsonify({"ok": True, "config": cc})

    except Exception as e:
        logger.error("Config upload failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/config", methods=["GET"])
def api_config_get():
    from company_config import load_config
    return jsonify(load_config())


@app.route("/api/config", methods=["POST"])
def api_config_save():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400
    try:
        from company_config import save_config, _normalize
        cc = _normalize(data)
        save_config(cc)
        _apply_config_to_runtime(cc)
        logger.info("Company config saved manually: company=%s", cc.get("company_name"))
        return jsonify({"ok": True, "config": cc})
    except Exception as e:
        logger.error("Config save failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/config/sample")
def api_config_sample():
    import os
    sample_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "company_brief.example.txt")
    if not os.path.exists(sample_path):
        return jsonify({"error": "Sample file not found"}), 404
    from flask import send_file
    return send_file(sample_path, as_attachment=True, download_name="company_brief_sample.txt")


# Legacy alias kept for backward compatibility
@app.route("/api/upload-brief", methods=["POST"])
def api_upload_brief():
    return api_config_upload()


@app.route("/api/brief")
def api_get_brief():
    import draft_emails as _de
    return jsonify({"context": _de.OMNITHRIVE_CONTEXT})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    start_background_thread()
    logger.info("Starting Lead-Gen dashboard on %s:%d", SERVER_HOST, SERVER_PORT)
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, threaded=True)
