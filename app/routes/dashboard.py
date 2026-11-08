from flask import Blueprint, Response, request

from app.store import get_store
from app.services.shift import detect_shift, get_shift_window, get_next_shift_window, get_previous_shift_window
from app.services.xlsx_parser import (
    safe_col, filter_snow_by_shift, filter_snow_by_status, filter_snow_by_recent,
    filter_spc_by_shift,
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
    mh, mr, _mm = store.get_source("spc_maxdb")

    ho_status = store.get_ho_status()

    source_meta = {}
    for key in ("snow_alert", "snow_case", "snow_inc", "spc", "spc_maxdb"):
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

    # Active Alerts subsection — last 24h updated, or manually pinned
    ar_active   = filter_snow_by_recent(ar, a_updated_idx, 16, a_link_idx, excluded=ar_excluded)
    ar_active   = apply_section_override(ar_active, ar, a_link_idx, overrides["alerts-active"], excluded=ar_excluded)

    ar_tbc_excluded = get_excluded_ids(ho_status, "alerts-tbc")
    ar_tbc = apply_section_override([], ar, a_link_idx, overrides["alerts-tbc"], excluded=ar_tbc_excluded)

    # Cases Updated in the last 16 hours subsection
    cr_active = filter_snow_by_recent(cr, c_updated_idx, 16, c_link_idx, excluded=cr_excluded)
    cr_active = apply_section_override(cr_active, cr, c_link_idx, overrides["cases-active"], excluded=cr_excluded)

    cr_tbc_excluded = get_excluded_ids(ho_status, "cases-tbc")
    cr_tbc = apply_section_override([], cr, c_link_idx, overrides["cases-tbc"], excluded=cr_tbc_excluded)

    # INCs Updated in the last 16 hours subsection
    ir_active = filter_snow_by_recent(ir, i_updated_idx, 16, i_link_idx, excluded=ir_excluded)
    ir_active = apply_section_override(ir_active, ir, i_link_idx, overrides["inc-active"], excluded=ir_excluded)

    ir_tbc_excluded = get_excluded_ids(ho_status, "inc-tbc")
    ir_tbc = apply_section_override([], ir, i_link_idx, overrides["inc-tbc"], excluded=ir_tbc_excluded)

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

    # Non-Core DB SPC subsections — mirrors SPC Tickets structure (prev/current/next/tbc/updated)
    m_link_idx = safe_col(mh, "Ticket ID")
    m_subj_idx = safe_col(mh, "Subject")
    m_lc_idx   = safe_col(mh, "Last Changed At")

    lr_flagged_maxdb    = get_flagged_ids(ho_status, "maxdb-tbc")
    hide_maxdb_current  = get_flagged_ids(ho_status, "maxdb-current")
    hide_maxdb_prev     = get_flagged_ids(ho_status, "maxdb-prev")
    hide_maxdb_next     = get_flagged_ids(ho_status, "maxdb-next")

    mr_current_excluded = get_excluded_ids(ho_status, "maxdb-current")
    mr_prev_excluded    = get_excluded_ids(ho_status, "maxdb-prev")
    mr_next_excluded    = get_excluded_ids(ho_status, "maxdb-next")
    mr_tbc_excluded     = get_excluded_ids(ho_status, "maxdb-tbc")
    mr_updated_excluded = get_excluded_ids(ho_status, "maxdb-updated")

    mr_current = filter_spc_by_shift(mr, m_subj_idx, shift_start, shift_end,
                                      m_link_idx, hide_maxdb_current, excluded=mr_current_excluded)
    mr_prev    = filter_spc_by_shift(mr, m_subj_idx, prev_start,  prev_end,
                                      m_link_idx, hide_maxdb_prev,    excluded=mr_prev_excluded)
    mr_next    = filter_spc_by_shift(mr, m_subj_idx, next_start,  next_end,
                                      m_link_idx, hide_maxdb_next,    excluded=mr_next_excluded)
    mr_tbc     = filter_spc_longrunners(mr, m_link_idx, lr_flagged_maxdb, excluded=mr_tbc_excluded)

    maxdb_scheduled_ids = {r[m_link_idx] for r in mr_current + mr_next
                           if m_link_idx < len(r) and r[m_link_idx]} | lr_flagged_maxdb
    mr_updated = filter_spc_by_last_changed(mr, m_lc_idx, prev_start, prev_end,
                                             m_link_idx, set(),
                                             exclude_ids=maxdb_scheduled_ids | mr_updated_excluded)

    mr_current = apply_section_override(mr_current, mr, m_link_idx, overrides["maxdb-current"], excluded=mr_current_excluded)
    mr_prev    = apply_section_override(mr_prev,    mr, m_link_idx, overrides["maxdb-prev"],    excluded=mr_prev_excluded)
    mr_next    = apply_section_override(mr_next,    mr, m_link_idx, overrides["maxdb-next"],    excluded=mr_next_excluded)
    mr_tbc     = apply_section_override(mr_tbc,     mr, m_link_idx, overrides["maxdb-tbc"],     excluded=mr_tbc_excluded)
    mr_updated = apply_section_override(mr_updated, mr, m_link_idx, overrides["maxdb-updated"], excluded=mr_updated_excluded)

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
        cr_tbc=cr_tbc,
        cr_all=cr,
        ar_active=ar_active,
        ar_tbc=ar_tbc,
        ar_all=ar,
        ir_active=ir_active,
        ir_tbc=ir_tbc,
        ir_all=ir,
        maxdb_headers=mh,
        maxdb_rows=mr,
        maxdb_rows_current=mr_current,
        maxdb_rows_prev=mr_prev,
        maxdb_rows_next=mr_next,
        maxdb_rows_tbc=mr_tbc,
        maxdb_rows_updated=mr_updated,
    )
    return Response(html, mimetype="text/html")
