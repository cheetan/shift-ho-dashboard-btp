import io

from flask import Blueprint, request, jsonify

from app.store import get_store
from app.services.xlsx_parser import read_snow_xlsx, read_spc_xlsx
from app.utils.auth import get_user_from_request
from app.config import get_upload_api_key

bp = Blueprint("api", __name__, url_prefix="/api")

SNOW_SOURCES = {"snow_alert", "snow_case", "snow_inc"}
ALL_SOURCES  = SNOW_SOURCES | {"spc"}


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
    return jsonify({
        src: (store.get_upload_meta(src) or {}).get("uploaded_at", "")
        for src in ("snow_alert", "snow_case", "snow_inc", "spc")
    })
