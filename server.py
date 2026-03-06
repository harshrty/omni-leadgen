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
import os

from flask import Flask, jsonify, request, send_from_directory

from config import SERVER_HOST, SERVER_PORT
from db import get_all_leads, get_lead_by_id, mark_opened
from email_sender import send_email
from reply_tracker import start_background_thread

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger(__name__)

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
        safe.append({
            "id": lead["id"],
            "company_name": lead.get("company_name") or "",
            "job_title": lead.get("job_title") or "",
            "job_description": (lead.get("job_description") or "")[:200],
            "tech_keywords": lead.get("tech_keywords") or "",
            "draft_subject": lead.get("draft_subject") or "",
            "draft_email": lead.get("draft_email") or "",
            "decision_maker_name": lead.get("decision_maker_name") or "",
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
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    start_background_thread()
    logger.info("Starting Omnithrive dashboard on %s:%d", SERVER_HOST, SERVER_PORT)
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False)
