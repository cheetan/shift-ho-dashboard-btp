import io
import urllib.request
import urllib.error
import json as _json

from flask import Blueprint, request, jsonify

from app.store import get_store
from app.services.xlsx_parser import read_snow_xlsx, read_spc_xlsx
from app.utils.auth import get_user_from_request
from app.config import get_upload_api_key, get_github_issues_token

bp = Blueprint("api", __name__, url_prefix="/api")

SNOW_SOURCES = {"snow_alert", "snow_case", "snow_inc"}
ALL_SOURCES  = SNOW_SOURCES | {"spc", "spc_maxdb"}


@bp.route("/upload/<source>", methods=["POST"])
def upload(source):
    expected = get_upload_api_key()
    if expected:
        has_bearer = request.headers.get("Authorization", "").startswith("Bearer ")
        has_key = request.headers.get("X-Upload-Key") == expected
        if not has_bearer and not has_key:
            return jsonify({"ok": False, "error": "Unauthorized"}), 401

    if source not in ALL_SOURCES:
        return jsonify({"ok": False, "error": f"Unknown source '{source}'"}), 400

    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file in request"}), 400

    uploaded_by = get_user_from_request(request)
    data = request.files["file"].read()

    try:
        if source in SNOW_SOURCES:
            headers, rows = read_snow_xlsx(io.BytesIO(data))
            meta = {}
        else:
            headers, rows, meta = read_spc_xlsx(io.BytesIO(data))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 422

    if not headers:
        return jsonify({"ok": False, "error": "Could not parse XLSX — empty or unrecognised format"}), 422

    get_store().upsert_source(source, headers, rows, uploaded_by, meta=meta)
    return jsonify({"ok": True, "source": source, "rows": len(rows)})


@bp.route("/export-notes", methods=["POST"])
def export_notes():
    notes = request.get_json(silent=True)
    if notes is None:
        return jsonify({"ok": False, "error": "Expected JSON body"}), 400

    updated_by = get_user_from_request(request)
    get_store().save_ho_status(notes, updated_by)
    return jsonify({"ok": True})


@bp.route("/ho-history/<ticket_id>", methods=["GET"])
def ho_history(ticket_id):
    return jsonify(get_store().get_ho_history(ticket_id))


@bp.route("/notify", methods=["POST"])
def notify():
    from app.config import get_ans_config
    ans = get_ans_config()
    if not ans.get("url") or not ans.get("client_id"):
        return jsonify({"ok": False, "error": "Alert Notification Service not bound — bind shift-ho-alerts in CF"}), 500

    from app.services.notify import build_shift_message, send_ans_event
    try:
        message, tags = build_shift_message(get_store())
        result  = send_ans_event(message, tags, ans["url"], ans["oauth_url"],
                                  ans["client_id"], ans["client_secret"])
        return jsonify({"ok": True, "message": message, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


@bp.route("/status", methods=["GET"])
def status():
    store = get_store()
    result = {
        src: (store.get_upload_meta(src) or {}).get("uploaded_at", "")
        for src in ("snow_alert", "snow_case", "snow_inc", "spc")
    }
    result["ho_status"] = store.get_ho_updated_at()
    return jsonify(result)


@bp.route("/feedback", methods=["POST"])
def feedback():
    token = get_github_issues_token()
    if not token:
        return jsonify({"ok": False, "error": "Feedback not configured"}), 503

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "Title is required"}), 400

    submitter = get_user_from_request(request)
    description = (data.get("description") or "").strip()
    issue_type = data.get("type", "bug")
    label = "bug" if issue_type == "bug" else "enhancement"
    body = f"**Submitted by:** {submitter}\n\n{description}" if description else f"**Submitted by:** {submitter}"

    payload = _json.dumps({"title": title, "body": body, "labels": [label]}).encode()
    req = urllib.request.Request(
        "https://api.github.com/repos/cheetan/shift-ho-dashboard-btp/issues",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = _json.loads(resp.read())
            return jsonify({"ok": True, "url": result["html_url"]})
    except urllib.error.HTTPError as e:
        return jsonify({"ok": False, "error": f"GitHub API error {e.code}"}), 502
