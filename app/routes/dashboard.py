from flask import Blueprint, Response, request

from app.store import get_store
from app.services.shift import detect_shift, get_shift_window, get_next_shift_window, get_previous_shift_window
from app.services.xlsx_parser import (
    safe_col, filter_snow_by_shift, filter_snow_by_status, filter_spc_by_shift,
    filter_spc_longrunners, filter_spc_by_last_changed, get_flagged_ids,
    get_section_overrides, apply_section_override, get_excluded_ids,
)
from app.services.dashboard_builder import build_html
from app.utils.auth import get_user_from_request

bp = Blueprint("dashboard", __name__)

ALLOWED_SHIFTS = {"night", "morning", "evening"}


@bp.route("/")
def index():
    store = get_store()

    ah, ar, _am = store.get_source("snow_alert")
    ch, cr, _cm = store.get_source("snow_case")
    ih, ir, _im = store.get_source("snow_inc")
    sh, sr_all_raw, sm = store.get_source("spc")

    ho_status = store.get_ho_status()

    source_meta = {}
    for key in ("snow_alert", "snow_case", "snow_inc", "spc"):
        source_meta[key] = store.get_upload_meta(key)

    shift_param = request.args.get("shift", "").lower()
    shift_name  = shift_param if shift_param in ALLOWED_SHIFTS else detect_shift()

    shift_label,      shift_start, shift_end   = get_shift_window(shift_name)
    next_label,       next_start,  next_end    = get_next_shift_window(shift_name)
    prev_label,       prev_start,  prev_end    = get_previous_shift_window(shift_name)

    a_updated_idx  = safe_col(ah, "Updated")
    a_link_idx     = safe_col(ah, "Number")
    c_updated_idx  = safe_col(ch, "Updated")
    c_link_idx     = safe_col(ch, "Number")
    i_updated_idx  = safe_col(ih, "Updated")
    i_link_idx     = safe_col(ih, "Number")
    s_subj_idx     = safe_col(sh, "Subject")
    s_link_idx     = safe_col(sh, "Ticket ID")
    s_lc_idx       = safe_col(sh, "Last Changed At")

    # Shift-filtered Snow rows
    ar_filtered = filter_snow_by_shift(ar, a_updated_idx, shift_start, shift_end, a_link_idx,
                                        get_flagged_ids(ho_status, "alerts"))
    cr_filtered = filter_snow_by_shift(cr, c_updated_idx, shift_start, shift_end, c_link_idx,
                                        get_flagged_ids(ho_status, "cases"))
    ir_filtered = filter_snow_by_shift(ir, i_updated_idx, shift_start, shift_end, i_link_idx,
                                        get_flagged_ids(ho_status, "inc"))

    overrides = get_section_overrides(ho_status)

    ar_excluded = get_excluded_ids(ho_status, "alerts-active")
    cr_excluded = get_excluded_ids(ho_status, "cases-active")
    ir_excluded = get_excluded_ids(ho_status, "inc-active")

    sr_current_excluded = get_excluded_ids(ho_status, "spc-current")
    sr_next_excluded    = get_excluded_ids(ho_status, "spc-next")
    sr_prev_excluded    = get_excluded_ids(ho_status, "spc-prev")
    sr_tbc_excluded     = get_excluded_ids(ho_status, "spc-tbc")
    sr_updated_excluded = get_excluded_ids(ho_status, "spc-updated")

    # Active Alerts subsection
    a_state_idx = safe_col(ah, "State")
    ar_active   = filter_snow_by_status(ar, a_state_idx, {"New", "In Progress"}, a_link_idx, set(), excluded=ar_excluded)
    ar_active   = apply_section_override(ar_active, ar, a_link_idx, overrides["alerts-active"], excluded=ar_excluded)

    # Active Cases subsection
    c_state_idx = safe_col(ch, "State")
    cr_active   = filter_snow_by_status(cr, c_state_idx, {"New", "In Progress"}, c_link_idx, set(), excluded=cr_excluded)
    cr_active   = apply_section_override(cr_active, cr, c_link_idx, overrides["cases-active"], excluded=cr_excluded)

    # Active INCs subsection
    i_state_idx = safe_col(ih, "State")
    ir_active   = filter_snow_by_status(ir, i_state_idx, {"New", "In Progress"}, i_link_idx, set(), excluded=ir_excluded)
    ir_active   = apply_section_override(ir_active, ir, i_link_idx, overrides["inc-active"], excluded=ir_excluded)

    # SPC sub-sections
    lr_flagged   = get_flagged_ids(ho_status, "spc-tbc")
    hide_current = get_flagged_ids(ho_status, "spc-current")
    hide_next    = get_flagged_ids(ho_status, "spc-next")
    hide_prev    = get_flagged_ids(ho_status, "spc-prev")

    sr_current = filter_spc_by_shift(sr_all_raw, s_subj_idx, shift_start, shift_end,
                                      s_link_idx, hide_current, excluded=sr_current_excluded)
    sr_next    = filter_spc_by_shift(sr_all_raw, s_subj_idx, next_start, next_end,
                                      s_link_idx, hide_next, excluded=sr_next_excluded)
    sr_prev    = filter_spc_by_shift(sr_all_raw, s_subj_idx, prev_start, prev_end,
                                      s_link_idx, hide_prev, excluded=sr_prev_excluded)
    sr_lr      = filter_spc_longrunners(sr_all_raw, s_link_idx, lr_flagged, excluded=sr_tbc_excluded)

    scheduled_ids = {r[s_link_idx] for r in sr_current + sr_next
                     if s_link_idx < len(r) and r[s_link_idx]}
    scheduled_ids |= lr_flagged
    sr_updated = filter_spc_by_last_changed(sr_all_raw, s_lc_idx, prev_start, prev_end,
                                             s_link_idx, set(), exclude_ids=scheduled_ids | sr_updated_excluded)

    sr_current = apply_section_override(sr_current, sr_all_raw, s_link_idx, overrides["spc-current"], excluded=sr_current_excluded)
    sr_next    = apply_section_override(sr_next,    sr_all_raw, s_link_idx, overrides["spc-next"],    excluded=sr_next_excluded)
    sr_lr      = apply_section_override(sr_lr,      sr_all_raw, s_link_idx, overrides["spc-tbc"],     excluded=sr_tbc_excluded)
    sr_updated = apply_section_override(sr_updated, sr_all_raw, s_link_idx, overrides["spc-updated"], excluded=sr_updated_excluded)
    sr_prev    = apply_section_override(sr_prev,    sr_all_raw, s_link_idx, overrides["spc-prev"],    excluded=sr_prev_excluded)

    current_user = get_user_from_request(request)
    ho_updated_at = get_store().get_ho_updated_at()

    html = build_html(
        ah, ar_filtered, ch, cr_filtered, ih, ir_filtered,
        sh, sr_all_raw, sr_current, sr_next, sr_lr, sr_updated, sm,
        ho_status=ho_status,
        shift_label=shift_label,
        next_shift_label=next_label,
        prev_shift_label=prev_label,
        source_meta=source_meta,
        current_user=current_user,
        ho_updated_at=ho_updated_at,
        sr_prev=sr_prev,
        cr_active=cr_active,
        cr_all=cr,
        ar_active=ar_active,
        ar_all=ar,
        ir_active=ir_active,
        ir_all=ir,
    )
    return Response(html, mimetype="text/html")
