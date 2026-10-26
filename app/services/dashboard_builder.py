import json
import re
from datetime import datetime, timezone

from app.services.shift import parse_spc_subject_dt
from app.services.xlsx_parser import safe_col


# ── priority helpers ──────────────────────────────────────────────────────────

def priority_rank(p):
    p = str(p).lower()
    if "1" in p or "very high" in p or "critical" in p: return 1
    if "2" in p or "high" in p or "urgent" in p:        return 2
    if "3" in p or "medium" in p or "normal" in p:      return 3
    if "4" in p or "low" in p:                          return 4
    return 5


def priority_class(p):
    return {1: "p1", 2: "p2", 3: "p3", 4: "p4"}.get(priority_rank(p), "p5")


def priority_label(p):
    return {1: "P1", 2: "P2", 3: "P3", 4: "P4"}.get(priority_rank(p), "—")


def count_by_priority(rows, pri_idx):
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for row in rows:
        r = priority_rank(row[pri_idx] if pri_idx < len(row) else "")
        if r in counts:
            counts[r] += 1
    return counts


def badge(text, cls):
    return f'<span class="badge {cls}">{text}</span>'


def reformat_date_dmy(val):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(str(val).strip()[:19], fmt).strftime("%d-%m-%Y %H:%M")
        except (ValueError, TypeError):
            pass
    return val


# ── table renderer ────────────────────────────────────────────────────────────

def render_table(headers, rows, show_cols, pri_col=None, link_col=None, rename=None,
                 link_url=None, col_format=None, sort_col=None, sort_desc=False,
                 editable_col=None, section_id="", longrunner=False, link_cols=None,
                 sort_key_fn=None, hideable=False, coverage_map=None):
    rename     = rename or {}
    col_format = col_format or {}
    link_cols  = link_cols or {}
    idxs   = [headers.index(h) for h in show_cols if h in headers]
    actual = [rename.get(headers[i], headers[i]) for i in idxs]
    pri_local = actual.index(rename.get(pri_col, pri_col)) if pri_col and rename.get(pri_col, pri_col) in actual else None
    link_raw  = headers.index(link_col) if link_col in headers else None

    if sort_key_fn:
        rows = sorted(rows, key=sort_key_fn)
    elif sort_col and sort_col in headers:
        sort_idx = headers.index(sort_col)
        rows = sorted(rows, key=lambda r: r[sort_idx] if sort_idx < len(r) else "", reverse=sort_desc)
    else:
        rows = sorted(rows, key=lambda r: priority_rank(r[headers.index(pri_col)] if pri_col in headers else ""))

    if not rows:
        return '<p class="empty">No tickets found.</p>'

    hide_th = '<th class="hide-th"></th>'          if hideable          else ""
    lr_th   = '<th class="lr-th">Longrunner</th>'  if longrunner        else ""
    extra_th = f'<th>{editable_col}</th>'           if editable_col      else ""
    cov_th  = '<th class="cov-th">Coverage</th>'   if coverage_map is not None else ""
    move_th = '<th class="move-th">Move to</th>'   if coverage_map is not None else ""
    th = hide_th + "".join(f"<th>{h}</th>" for h in actual) + lr_th + extra_th + cov_th + move_th

    tbody = []
    for row in rows:
        p_val = row[headers.index(pri_col)] if pri_col in headers else ""
        pcls  = priority_class(p_val)
        tds   = []
        for local_i, raw_i in enumerate(idxs):
            val = row[raw_i] if raw_i < len(row) else ""
            raw_col_name = headers[raw_i]
            if raw_col_name in col_format:
                val = col_format[raw_col_name](val)
            if local_i == pri_local:
                cell = badge(priority_label(val), pcls)
            elif raw_col_name in link_cols and val:
                href = link_cols[raw_col_name].format(val)
                cell = f'<a class="ticket-num" href="{href}" target="_blank" rel="noopener">{val}</a>'
            elif raw_i == link_raw and val:
                if link_url:
                    href = link_url.format(val)
                    cell = f'<a class="ticket-num" href="{href}" target="_blank" rel="noopener">{val}</a>'
                else:
                    cell = f'<span class="ticket-num">{val}</span>'
            else:
                cell = val or "—"
            tds.append(f"<td>{cell}</td>")

        ticket_key = row[link_raw] if link_raw is not None and link_raw < len(row) else ""

        if hideable:
            hide_key = f"hide:{section_id}:{ticket_key}"
            hide_td = f'<td class="hide-td"><button class="hide-btn" data-key="{hide_key}" onclick="hideRow(this)" title="Remove from view">&#x2715;</button></td>'
        else:
            hide_td = ""

        if longrunner:
            lr_key = f"lr:{section_id}:{ticket_key}"
            tds.append(f'<td class="lr-td"><input type="checkbox" class="lr-flag" data-key="{lr_key}" onchange="saveLR(this)"></td>')
        if editable_col:
            ho_key = f"ho:{section_id}:{ticket_key}"
            tds.append(f'<td><div class="ho-edit" contenteditable="true" data-key="{ho_key}" oninput="saveHO(this)"></div></td>')
        if coverage_map is not None:
            cov_label = coverage_map.get(ticket_key, "") if ticket_key else ""
            if cov_label:
                _cov_cls = {"Current Shift": "cov-current", "Next Shift": "cov-next",
                            "Longrunner": "cov-lr", "Updated": "cov-updated"}.get(cov_label, "")
                cov_cell = f'<span class="cov-badge {_cov_cls}">{cov_label}</span>'
            else:
                cov_cell = '<span class="cov-none">—</span>'
            tds.append(f"<td>{cov_cell}</td>")
            tds.append(
                f'<td><select class="move-select" data-ticket="{ticket_key}" onchange="moveTicket(this)">'
                f'<option value="">— auto —</option>'
                f'<option value="spc-current">Current Shift</option>'
                f'<option value="spc-next">Next Shift</option>'
                f'<option value="spc-lr">Longrunners</option>'
                f'<option value="spc-updated">Updated</option>'
                f'</select></td>'
            )

        row_covered_cls = " row-covered" if (coverage_map is not None and ticket_key and ticket_key in coverage_map) else ""
        tbody.append(f'<tr class="row-{pcls}{row_covered_cls}" data-hide-key="{f"hide:{section_id}:{ticket_key}" if hideable else ""}">{hide_td}{"".join(tds)}</tr>')

    return f'<div class="table-wrap"><table><thead><tr>{th}</tr></thead><tbody>{"".join(tbody)}</tbody></table></div>'


def stat_tile(label, total, pcounts):
    p1, p2 = pcounts.get(1, 0), pcounts.get(2, 0)
    pills = ""
    if p1: pills += f'<span class="badge p1">P1: {p1}</span>'
    if p2: pills += f'<span class="badge p2">P2: {p2}</span>'
    hi = " hi" if p1 or p2 else ""
    return f"""<div class="stat-tile{hi}">
  <div class="stat-num">{total}</div>
  <div class="stat-label">{label}</div>
  <div class="stat-pills">{pills or '<span class="ok">All P3/P4</span>'}</div>
</div>"""


def _fresh_bar_item(source_key, label, source_meta):
    m = (source_meta or {}).get(source_key, {})
    by       = m.get("uploaded_by", "—")
    at       = m.get("uploaded_at", "—")
    count    = m.get("row_count", 0)
    by_short = by.split("@")[0] if "@" in by else by
    return f"""<div class="fresh-item">
  <div class="fresh-info">
    <span class="fresh-label">{label}</span>
    <span class="fresh-count">{count} rows</span>
    <span class="fresh-who">by {by_short} at {at}</span>
  </div>
  <label class="upload-btn" title="Upload new {label} XLSX">
    &#x1F4E4; Upload<input type="file" accept=".xlsx" style="display:none" onchange="uploadFile(this,'{source_key}')">
  </label>
</div>"""


# ── main HTML builder ─────────────────────────────────────────────────────────

def build_html(ah, ar, ch, cr, ih, ir, sh, sr_all_raw, sr_current, sr_next, sr_lr, sr_updated, sm,
               ho_status=None, shift_label="", next_shift_label="", prev_shift_label="",
               source_meta=None, current_user=""):
    now       = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    spc_updated_str = sm.get("last_updated", "—") + " " + sm.get("timezone", "")
    ho_json   = json.dumps(ho_status or {}, ensure_ascii=False)

    a_pri = safe_col(ah, "Priority"); c_pri = safe_col(ch, "Priority")
    s_pri = safe_col(sh, "Priority"); i_pri = safe_col(ih, "Priority")

    sr_all = sr_current + sr_next + sr_lr + sr_updated
    apc  = count_by_priority(ar, a_pri)
    cpc  = count_by_priority(cr, c_pri)
    ipc  = count_by_priority(ir, i_pri)
    spc_c = count_by_priority(sr_all, s_pri)

    sched_activities = len(sr_current) + len(sr_next)

    snow_url    = "https://itsm.services.sap//workspace_redirect.do?sysparm_number={}"
    snow_rename = {"Install Base Item": "SIDCID", "Number": "Ticket ID",
                   "Assigned to": "Processor", "Updated": "Last Updated EET"}

    alert_t = render_table(
        ah, ar,
        [c for c in ["Number","Priority","State","Assigned to","Subject","Install Base Item","Updated"] if c in ah],
        pri_col="Priority", link_col="Number", rename=snow_rename, link_url=snow_url,
        col_format={"Updated": reformat_date_dmy}, sort_col="Updated", sort_desc=True,
        editable_col="HO Status", section_id="alerts", longrunner=True, hideable=True)

    case_t = render_table(
        ch, cr,
        [c for c in ["Number","Priority","State","Assigned to","Subject","Install Base Item","Used for","Updated"] if c in ch],
        pri_col="Priority", link_col="Number", rename=snow_rename, link_url=snow_url,
        col_format={"Updated": reformat_date_dmy}, sort_col="Updated", sort_desc=True,
        editable_col="HO Status", section_id="cases", longrunner=True, hideable=True)

    inc_t = render_table(
        ih, ir,
        [c for c in ["Number","Priority","State","Assigned to","Short description","Subject","Install Base Item","Updated"] if c in ih],
        pri_col="Priority", link_col="Number", rename=snow_rename, link_url=snow_url,
        col_format={"Updated": reformat_date_dmy}, sort_col="Updated", sort_desc=True,
        editable_col="HO Status", section_id="inc", longrunner=True, hideable=True)

    spc_cols = [c for c in ["Ticket ID","Ticket Type","Priority","Status","Processor","Subject",
                             "Last Changed At","Service Execution ID","Process Execution ID",
                             "Process Execution Status"] if c in sh]
    spc_rename     = {"Service Execution ID": "SE ID", "Process Execution ID": "PID ID",
                      "Process Execution Status": "PID Status"}
    spc_multi_links = {"Service Execution ID": "https://spc.ondemand.com/open?SRVEXE={}",
                       "Process Execution ID":  "https://spc.ondemand.com/open?pri={}"}
    spc_col_fmt    = {"Last Changed At": reformat_date_dmy}
    s_subj_idx     = safe_col(sh, "Subject")
    _dt_min        = datetime.min.replace(tzinfo=timezone.utc)

    def spc_subj_sort(r):
        return parse_spc_subject_dt(r[s_subj_idx] if s_subj_idx < len(r) else "") or _dt_min

    spc_current_t = render_table(sh, sr_current, spc_cols,
        pri_col="Priority", link_col="Ticket ID", link_url="https://spc.ondemand.com/open?ticket={}",
        rename=spc_rename, link_cols=spc_multi_links, col_format=spc_col_fmt,
        editable_col="HO Status", section_id="spc-current", longrunner=True,
        sort_key_fn=spc_subj_sort, hideable=True)
    spc_next_t = render_table(sh, sr_next, spc_cols,
        pri_col="Priority", link_col="Ticket ID", link_url="https://spc.ondemand.com/open?ticket={}",
        rename=spc_rename, link_cols=spc_multi_links, col_format=spc_col_fmt,
        editable_col="HO Status", section_id="spc-next", longrunner=True,
        sort_key_fn=spc_subj_sort, hideable=True)
    spc_lr_t = render_table(sh, sr_lr, spc_cols,
        pri_col="Priority", link_col="Ticket ID", link_url="https://spc.ondemand.com/open?ticket={}",
        rename=spc_rename, link_cols=spc_multi_links, col_format=spc_col_fmt,
        editable_col="HO Status", section_id="spc-lr", longrunner=True, hideable=True)
    spc_updated_t = render_table(sh, sr_updated, spc_cols,
        pri_col="Priority", link_col="Ticket ID", link_url="https://spc.ondemand.com/open?ticket={}",
        rename=spc_rename, link_cols=spc_multi_links, col_format=spc_col_fmt,
        sort_col="Last Changed At", sort_desc=True,
        editable_col="HO Status", section_id="spc-updated", longrunner=True, hideable=True)

    spc_link_idx = safe_col(sh, "Ticket ID")
    coverage = {}
    for _r in sr_current:
        _tid = _r[spc_link_idx] if spc_link_idx < len(_r) else ""
        if _tid and _tid not in coverage: coverage[_tid] = "Current Shift"
    for _r in sr_next:
        _tid = _r[spc_link_idx] if spc_link_idx < len(_r) else ""
        if _tid and _tid not in coverage: coverage[_tid] = "Next Shift"
    for _r in sr_lr:
        _tid = _r[spc_link_idx] if spc_link_idx < len(_r) else ""
        if _tid and _tid not in coverage: coverage[_tid] = "Longrunner"
    for _r in sr_updated:
        _tid = _r[spc_link_idx] if spc_link_idx < len(_r) else ""
        if _tid and _tid not in coverage: coverage[_tid] = "Updated"
    spc_all_t = render_table(sh, sr_all_raw, spc_cols,
        pri_col="Priority", link_col="Ticket ID", link_url="https://spc.ondemand.com/open?ticket={}",
        rename=spc_rename, link_cols=spc_multi_links, col_format=spc_col_fmt,
        sort_col="Last Changed At", sort_desc=True,
        editable_col="HO Status", section_id="spc-all", hideable=True,
        coverage_map=coverage)

    fresh_bar = (
        _fresh_bar_item("snow_alert", "Snow Alerts", source_meta) +
        _fresh_bar_item("snow_case",  "Snow Cases",  source_meta) +
        _fresh_bar_item("snow_inc",   "Snow INCs",   source_meta) +
        _fresh_bar_item("spc",        "SPC Report",  source_meta)
    )

    def section(sid, icon, title, count, table_html, subtitle=""):
        sub_html = f'<span class="section-sub">{subtitle}</span>' if subtitle else ""
        return f"""
<div class="section">
  <div class="section-header" onclick="toggle('{sid}')">
    <span class="icon">{icon}</span>
    <h2>{title}</h2>{sub_html}
    <span class="count">{count}</span>
    <span class="toggle" id="{sid}-tog">&#9660;</span>
  </div>
  <div class="section-body" id="{sid}">
    <div class="filter-bar">
      <input type="text" placeholder="Filter&hellip;" oninput="filterText('{sid}-tbl', this.value)">
      <button class="filter-btn" onclick="filterPri('{sid}-tbl','p1',this)">P1</button>
      <button class="filter-btn" onclick="filterPri('{sid}-tbl','p2',this)">P2</button>
      <button class="filter-btn" onclick="filterPri('{sid}-tbl','p3',this)">P3</button>
      <button class="filter-btn" onclick="filterPri('{sid}-tbl','p4',this)">P4</button>
      <button class="filter-btn show-hidden-btn" data-tbl="{sid}-tbl" data-showing="0" onclick="toggleHidden(this)">Show hidden (0)</button>
    </div>
    <div id="{sid}-tbl">{table_html}</div>
  </div>
</div>"""

    def subsection(ssid, icon, title, count, table_html):
        return f"""
<div class="subsection">
  <div class="subsection-header" onclick="toggle('{ssid}')">
    <span class="icon">{icon}</span>
    <h3>{title}</h3>
    <span class="count">{count}</span>
    <span class="toggle" id="{ssid}-tog">&#9660;</span>
  </div>
  <div id="{ssid}">
    <div class="subsection-filter">
      <input type="text" placeholder="Filter&hellip;" oninput="filterText('{ssid}-tbl', this.value)">
      <button class="filter-btn" onclick="filterPri('{ssid}-tbl','p1',this)">P1</button>
      <button class="filter-btn" onclick="filterPri('{ssid}-tbl','p2',this)">P2</button>
      <button class="filter-btn" onclick="filterPri('{ssid}-tbl','p3',this)">P3</button>
      <button class="filter-btn" onclick="filterPri('{ssid}-tbl','p4',this)">P4</button>
      <button class="filter-btn show-hidden-btn" data-tbl="{ssid}-tbl" data-showing="0" onclick="toggleHidden(this)">Show hidden (0)</button>
    </div>
    <div id="{ssid}-tbl">{table_html}</div>
  </div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shift Handover Dashboard EU DB L2</title>
<style>
:root {{
  --bg:#0f1117; --surface:#1a1d27; --border:#2a2d3a;
  --text:#e2e4f0; --muted:#7c8099;
  --p1:#ff4d4f; --p2:#fa8c16; --p3:#c8a800; --p4:#52c41a;
  --p1-bg:rgba(255,77,79,.10); --p2-bg:rgba(250,140,22,.08);
  --p3-bg:rgba(250,219,20,.04); --p4-bg:rgba(82,196,26,.04);
  --accent:#4f8ef7;
  --font:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px}}
header{{padding:16px 24px 12px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}}
header h1{{font-size:18px;font-weight:600;color:#fff}}
.shift-label{{font-size:13px;font-weight:500;color:var(--accent);flex:1;padding-left:16px}}
header .meta{{font-size:11px;color:var(--muted);text-align:right;line-height:1.7;margin-left:auto}}
.user-pill{{font-size:11px;color:var(--muted);cursor:pointer;padding:4px 8px;border:1px solid var(--border);border-radius:6px;white-space:nowrap}}
.user-pill:hover{{border-color:var(--accent);color:var(--accent)}}
.export-btn{{background:var(--surface);border:1px solid var(--border);color:var(--text);border-radius:7px;padding:6px 14px;font-size:12px;cursor:pointer;white-space:nowrap}}
.export-btn:hover{{border-color:var(--accent);color:var(--accent)}}
main{{padding:20px 24px}}
.freshness-bar{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}
.fresh-item{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 12px;display:flex;align-items:center;gap:10px;flex:1;min-width:200px}}
.fresh-info{{display:flex;flex-direction:column;gap:2px;flex:1;min-width:0}}
.fresh-label{{font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}}
.fresh-count{{font-size:15px;font-weight:700;color:var(--accent);line-height:1}}
.fresh-who{{font-size:10px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.upload-btn{{background:var(--border);border:1px solid transparent;color:var(--muted);border-radius:6px;padding:5px 10px;font-size:11px;cursor:pointer;white-space:nowrap;display:inline-flex;align-items:center;gap:4px}}
.upload-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.upload-btn.uploading{{color:var(--p3);border-color:var(--p3)}}
.ho-bar{{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap}}
.ho-pill{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 16px;font-size:12px;color:var(--muted)}}
.ho-pill strong{{color:var(--text);font-size:22px;display:block;line-height:1.2}}
.ho-pill.hi{{border-color:var(--p2)}}
.ho-pill.hi strong{{color:var(--p2)}}
.stats{{display:flex;gap:10px;margin-bottom:22px;flex-wrap:wrap}}
.stat-tile{{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 18px;min-width:150px;flex:1}}
.stat-tile.hi{{border-color:rgba(250,140,22,.4)}}
.stat-num{{font-size:34px;font-weight:700;color:#fff;line-height:1}}
.stat-label{{font-size:11px;color:var(--muted);margin:4px 0 8px;text-transform:uppercase;letter-spacing:.05em}}
.stat-pills{{display:flex;gap:6px;flex-wrap:wrap}}
.ok{{font-size:11px;color:var(--p4)}}
.section{{margin-bottom:20px}}
.section-header{{display:flex;align-items:center;gap:10px;margin-bottom:8px;cursor:pointer;user-select:none}}
.section-header h2{{font-size:14px;font-weight:600}}
.section-sub{{font-size:11px;color:var(--muted);margin-left:6px;font-weight:400}}
.section-header .count{{background:var(--border);border-radius:12px;padding:1px 8px;font-size:11px;color:var(--muted)}}
.section-header .toggle{{margin-left:auto;color:var(--muted);font-size:11px}}
.section-body{{background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden}}
.filter-bar{{display:flex;gap:6px;padding:8px 12px;border-bottom:1px solid var(--border);flex-wrap:wrap;align-items:center}}
.filter-bar input{{background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:4px 10px;font-size:12px;width:190px;outline:none}}
.filter-bar input:focus{{border-color:var(--accent)}}
.filter-btn{{background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:6px;padding:3px 10px;font-size:11px;cursor:pointer}}
.filter-btn.active{{border-color:var(--accent);color:var(--accent)}}
.table-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse}}
th{{background:#12141e;color:var(--muted);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;padding:8px 12px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}}
td{{padding:7px 12px;border-bottom:1px solid var(--border);vertical-align:top;line-height:1.4;max-width:340px;word-break:break-word}}
tr:last-child td{{border-bottom:none}}
tr.row-p1{{background:var(--p1-bg)}}
tr.row-p2{{background:var(--p2-bg)}}
tr.row-p3{{background:var(--p3-bg)}}
tr.row-p4{{background:var(--p4-bg)}}
.ticket-num{{font-family:monospace;font-size:12px;color:var(--accent);text-decoration:none}}
.ticket-num:hover{{text-decoration:underline}}
.ho-edit{{min-width:130px;min-height:20px;padding:3px 6px;border:1px dashed var(--border);border-radius:4px;outline:none;cursor:text;white-space:pre-wrap;word-break:break-word;color:var(--text)}}
.ho-edit:focus{{border-color:var(--accent);background:rgba(79,142,247,.08)}}
.ho-edit:not(:empty){{border-style:solid;border-color:rgba(79,142,247,.35)}}
.lr-th{{width:80px;text-align:center}}
.lr-td{{text-align:center;vertical-align:middle}}
.lr-flag{{width:16px;height:16px;cursor:pointer;accent-color:var(--accent)}}
.info-area-wrap{{padding:12px}}
.info-area{{min-height:140px;padding:12px 14px;background:var(--bg);border:1px dashed var(--border);border-radius:6px;color:var(--text);font-size:13px;line-height:1.7;outline:none;white-space:pre-wrap;word-break:break-word}}
.info-area:focus{{border-color:var(--accent);border-style:solid}}
.info-area:not(:empty){{border-style:solid;border-color:rgba(79,142,247,.35)}}
.info-area[placeholder]:empty:before{{content:attr(placeholder);color:var(--muted);pointer-events:none}}
.badge{{display:inline-block;border-radius:4px;padding:1px 7px;font-size:11px;font-weight:700}}
.p1{{background:rgba(255,77,79,.20);color:var(--p1)}}
.p2{{background:rgba(250,140,22,.20);color:var(--p2)}}
.p3{{background:rgba(250,219,20,.20);color:var(--p3)}}
.p4{{background:rgba(82,196,26,.20);color:var(--p4)}}
.p5{{background:var(--border);color:var(--muted)}}
.empty{{padding:20px;color:var(--muted);font-style:italic}}
.icon{{font-size:15px}}
.subsection{{border-top:1px solid var(--border)}}
.subsection:first-child{{border-top:none}}
.subsection-header{{display:flex;align-items:center;gap:10px;padding:8px 14px;cursor:pointer;user-select:none;background:rgba(255,255,255,.025)}}
.subsection-header h3{{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}}
.subsection-header .count{{background:var(--border);border-radius:12px;padding:1px 8px;font-size:11px;color:var(--muted)}}
.subsection-header .toggle{{margin-left:auto;color:var(--muted);font-size:11px}}
.subsection-filter{{display:flex;gap:6px;padding:8px 12px;border-bottom:1px solid var(--border);flex-wrap:wrap;align-items:center}}
.subsection-filter input{{background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:4px 10px;font-size:12px;width:190px;outline:none}}
.subsection-filter input:focus{{border-color:var(--accent)}}
.hide-th{{width:28px;padding:0}}
.hide-td{{text-align:center;vertical-align:middle;padding:0 4px}}
.hide-btn{{background:transparent;border:none;color:var(--muted);cursor:pointer;font-size:13px;padding:3px 5px;border-radius:4px;line-height:1}}
.hide-btn:hover{{color:var(--p1);background:rgba(255,77,79,.15)}}
tr.row-hidden{{opacity:.5;background:repeating-linear-gradient(135deg,transparent,transparent 6px,rgba(255,77,79,.06) 6px,rgba(255,77,79,.06) 12px) !important}}
.cov-th{{width:110px}}
.cov-badge{{display:inline-block;border-radius:4px;padding:1px 7px;font-size:10px;font-weight:600;white-space:nowrap}}
.cov-current{{background:rgba(82,196,26,.20);color:#52c41a}}
.cov-next{{background:rgba(250,219,20,.20);color:#c8a800}}
.cov-lr{{background:rgba(255,77,79,.20);color:#ff4d4f}}
.cov-updated{{background:rgba(79,142,247,.20);color:#4f8ef7}}
.cov-none{{color:var(--muted)}}
.move-th{{width:120px}}
.move-select{{font-size:11px;padding:2px 4px;border-radius:4px;border:1px solid var(--border);background:var(--bg);color:var(--text);cursor:pointer;width:100%}}
tr.row-covered{{opacity:.4}}
tr.row-covered:hover{{opacity:1;transition:opacity .15s}}
.hide-covered tr.row-covered{{display:none}}
.save-indicator{{position:fixed;bottom:24px;right:24px;background:#1a2e1a;border:2px solid #52c41a;color:#52c41a;border-radius:10px;padding:12px 20px;font-size:14px;font-weight:600;opacity:0;transform:translateY(10px);transition:opacity .3s,transform .3s;pointer-events:none;box-shadow:0 4px 20px rgba(82,196,26,.35);letter-spacing:.02em;z-index:9999}}
.save-indicator.show{{opacity:1;transform:translateY(0)}}
</style>
</head>
<body>
<header>
  <h1>&#x1F4CB; Shift Handover Dashboard EU DB L2</h1>
  <div class="shift-label">{shift_label}</div>
  <div class="meta">Generated: {now}<br>SPC data: {spc_updated_str}</div>
  <span class="user-pill" onclick="changeEmail()" title="Click to change your email">&#x1F464; <span id="user-email-display">—</span></span>
  <button class="export-btn" onclick="exportNotes()">&#x1F4BE; Export &amp; Save Notes</button>
  <button class="export-btn" id="notify-btn" onclick="notifyTeam(this)">&#x1F514; Notify Team</button>
</header>
<main>

<div class="freshness-bar">
{fresh_bar}
</div>

<div class="ho-bar">
  <div class="ho-pill {'hi' if sched_activities else ''}"><strong>{sched_activities}</strong>&#x1F4C5; Scheduled Activities</div>
</div>

<div class="stats">
  {stat_tile("Snow Cases",  len(cr), cpc)}
  {stat_tile("Snow Alerts", len(ar), apc)}
  {stat_tile("Snow Internal INCs", len(ir), ipc)}
  {stat_tile("SPC Tickets Updated Former Shift", len(sr_updated), spc_c)}
</div>

{section("cases",  "&#x1F4CB;",        "Snow Cases",          len(cr), case_t,  subtitle=shift_label)}
{section("alerts", "&#x26A0;&#xFE0F;", "Snow Alerts",         len(ar), alert_t, subtitle=shift_label)}
{section("inc",    "&#x1F6A8;",        "Snow Internal INCs",  len(ir), inc_t,   subtitle=shift_label)}

<div class="section">
  <div class="section-header" onclick="toggle('spc')">
    <span class="icon">&#x1F5A5;&#xFE0F;</span>
    <h2>SPC Tickets</h2>
    <span class="section-sub">{shift_label}</span>
    <span class="count">{len(sr_all)}</span>
    <span class="toggle" id="spc-tog">&#9660;</span>
  </div>
  <div class="section-body" id="spc">
    {subsection("spc-current", "&#x1F7E2;", f"Current Shift &mdash; {shift_label}", len(sr_current), spc_current_t)}
    {subsection("spc-next",    "&#x1F7E1;", f"Next Shift &mdash; {next_shift_label}", len(sr_next), spc_next_t)}
    {subsection("spc-lr",      "&#x1F534;", "Longrunners", len(sr_lr), spc_lr_t)}
    {subsection("spc-updated", "&#x1F504;", f"Tickets Updated on Former Shift &mdash; {shift_label}", len(sr_updated), spc_updated_t)}
  </div>
</div>

<div class="section">
  <div class="section-header" onclick="toggle('spc-all')">
    <span class="icon">&#x1F4C2;</span>
    <h2>All SPC Tickets</h2>
    <span class="section-sub">Complete XLSX &mdash; {len(sr_all_raw)} tickets</span>
    <span class="count">{len(sr_all_raw)}</span>
    <span class="toggle" id="spc-all-tog">&#9654;</span>
  </div>
  <div class="section-body" id="spc-all" style="display:none">
    <div class="filter-bar">
      <input type="text" placeholder="Filter&hellip;" oninput="filterText('spc-all-tbl', this.value)">
      <button class="filter-btn" onclick="filterPri('spc-all-tbl','p1',this)">P1</button>
      <button class="filter-btn" onclick="filterPri('spc-all-tbl','p2',this)">P2</button>
      <button class="filter-btn" onclick="filterPri('spc-all-tbl','p3',this)">P3</button>
      <button class="filter-btn" onclick="filterPri('spc-all-tbl','p4',this)">P4</button>
      <button class="filter-btn show-hidden-btn" data-tbl="spc-all-tbl" data-showing="0" onclick="toggleHidden(this)">Show hidden (0)</button>
      <button class="filter-btn toggle-covered-btn" data-tbl="spc-all-tbl" data-hiding="0" onclick="toggleCovered(this)">Show only uncovered (0)</button>
    </div>
    <div id="spc-all-tbl">{spc_all_t}</div>
  </div>
</div>

<div class="section">
  <div class="section-header" onclick="toggle('info')">
    <span class="icon">&#x2139;&#xFE0F;</span>
    <h2>Information</h2>
    <span class="toggle" id="info-tog">&#9660;</span>
  </div>
  <div class="section-body" id="info">
    <div class="info-area-wrap">
      <div class="info-area" id="info-area" contenteditable="true"
           placeholder="Type here — notes, tasks, anything the team should be aware of&hellip;"
           oninput="saveInfo()"></div>
    </div>
  </div>
</div>

</main>
<div class="save-indicator" id="save-indicator">&#x2713; Notes saved</div>
<script>
var sharedNotes = {ho_json};

var _autoSaveTimer = null;
function _scheduleAutoSave() {{
  if (_autoSaveTimer) clearTimeout(_autoSaveTimer);
  _autoSaveTimer = setTimeout(function() {{ _serverSave(false); }}, 1500);
}}
function saveHO(el) {{
  localStorage.setItem(el.dataset.key, el.innerText);
  _scheduleAutoSave();
}}
function saveLR(el) {{
  if (el.checked) localStorage.setItem(el.dataset.key, '1');
  else            localStorage.removeItem(el.dataset.key);
  _scheduleAutoSave();
}}
function moveTicket(sel) {{
  _scheduleAutoSave();
}}
function saveInfo() {{
  localStorage.setItem('info:notes', document.getElementById('info-area').innerText);
  _scheduleAutoSave();
}}
function _serverSave(showIndicator) {{
  var notes = _collectNotes();
  var email = localStorage.getItem('user_email') || 'unknown';
  fetch('/api/export-notes', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json', 'X-User-Email': email}},
    body: JSON.stringify(notes)
  }}).then(function(r) {{
    if (r.ok) {{ if (showIndicator) showSaved(); }}
    else {{ console.warn('Server save failed: HTTP ' + r.status); showSaveError(r.status); }}
  }}).catch(function(e) {{ console.warn('Auto-save error:', e); showSaveError(0); }});
}}
function hideRow(btn) {{
  var tr = btn.closest('tr');
  var key = btn.dataset.key;
  var tblDiv = tr.closest('div[id$="-tbl"]');
  if (tr.classList.contains('row-hidden')) {{
    localStorage.removeItem(key);
    tr.classList.remove('row-hidden');
    tr.style.display = '';
    btn.innerHTML = '&#x2715;';
    btn.title = 'Remove from view';
  }} else {{
    localStorage.setItem(key, '1');
    tr.classList.add('row-hidden');
    tr.style.display = 'none';
  }}
  if (tblDiv) updateHiddenBtn(tblDiv.id);
}}
function updateHiddenBtn(tblId) {{
  var btn = document.querySelector('.show-hidden-btn[data-tbl="' + tblId + '"]');
  if (btn && btn.dataset.showing !== '1') {{
    var cnt = document.getElementById(tblId).querySelectorAll('tr.row-hidden').length;
    btn.textContent = 'Show hidden (' + cnt + ')';
  }}
}}
function toggleHidden(btn) {{
  var tbl = document.getElementById(btn.dataset.tbl);
  var rows = tbl.querySelectorAll('tr.row-hidden');
  var showing = btn.dataset.showing === '1';
  rows.forEach(function(r) {{
    r.style.display = showing ? 'none' : '';
    var hb = r.querySelector('.hide-btn');
    if (hb) {{ hb.innerHTML = showing ? '&#x2715;' : '&#x21A9;'; hb.title = showing ? 'Remove from view' : 'Restore to view'; }}
  }});
  btn.dataset.showing = showing ? '0' : '1';
  btn.textContent = (showing ? 'Show hidden' : 'Hide hidden') + ' (' + rows.length + ')';
  btn.classList.toggle('active', !showing);
}}
function toggleCovered(btn) {{
  var tbl = document.getElementById(btn.dataset.tbl);
  var hiding = btn.dataset.hiding !== '1';
  if (hiding) {{ tbl.classList.add('hide-covered'); }}
  else        {{ tbl.classList.remove('hide-covered'); }}
  btn.dataset.hiding = hiding ? '1' : '0';
  var uncovered = tbl.querySelectorAll('tbody tr:not(.row-covered):not(.row-hidden)').length;
  btn.textContent = (hiding ? 'Show all' : 'Show only uncovered') + ' (' + uncovered + ' uncovered)';
  btn.classList.toggle('active', hiding);
}}
function _collectNotes() {{
  var notes = Object.assign({{}}, sharedNotes);
  document.querySelectorAll('.ho-edit').forEach(function(el) {{
    var key = el.dataset.key; var val = el.innerText.trim();
    if (val) notes[key] = val; else delete notes[key];
  }});
  document.querySelectorAll('.lr-flag').forEach(function(el) {{
    var key = el.dataset.key;
    if (el.checked) notes[key] = '1'; else delete notes[key];
  }});
  document.querySelectorAll('.move-select').forEach(function(el) {{
    var tid = el.dataset.ticket;
    ['spc-current','spc-next','spc-lr','spc-updated'].forEach(function(s) {{
      delete notes['move:' + s + ':' + tid];
    }});
    if (el.value) notes['move:' + el.value + ':' + tid] = '1';
  }});
  Object.keys(notes).forEach(function(k) {{ if (k.startsWith('hide:')) delete notes[k]; }});
  var infoVal = document.getElementById('info-area').innerText.trim();
  if (infoVal) notes['info:notes'] = infoVal; else delete notes['info:notes'];
  return notes;
}}
function exportNotes() {{
  var notes = _collectNotes();
  var blob = new Blob([JSON.stringify(notes, null, 2)], {{type: 'application/json'}});
  var a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = 'ho_status.json'; a.click(); URL.revokeObjectURL(a.href);
  _serverSave(true);
}}
function notifyTeam(btn) {{
  btn.disabled = true; btn.textContent = '⏳ Sending…';
  fetch('/api/notify', {{
    method: 'POST',
    headers: {{'X-User-Email': localStorage.getItem('user_email') || 'unknown'}}
  }}).then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      btn.disabled = false;
      btn.innerHTML = d.ok ? '&#x2705; Notified!' : '&#x274C; Failed';
      setTimeout(function() {{ btn.innerHTML = '&#x1F514; Notify Team'; }}, 3000);
    }}).catch(function() {{
      btn.disabled = false; btn.innerHTML = '&#x274C; Error';
      setTimeout(function() {{ btn.innerHTML = '&#x1F514; Notify Team'; }}, 3000);
    }});
}}
function showSaved() {{
  var el = document.getElementById('save-indicator');
  el.classList.add('show');
  setTimeout(function() {{ el.classList.remove('show'); }}, 2500);
}}
function showSaveError(status) {{
  var el = document.getElementById('save-indicator');
  el.textContent = '&#x26A0; Save failed' + (status ? ' (' + status + ')' : '');
  el.style.borderColor = 'var(--p1)'; el.style.color = 'var(--p1)';
  el.classList.add('show');
  setTimeout(function() {{
    el.classList.remove('show');
    el.textContent = '&#x2713; Notes saved';
    el.style.borderColor = ''; el.style.color = '';
  }}, 4000);
}}
function uploadFile(input, source) {{
  if (!input.files[0]) return;
  var email = localStorage.getItem('user_email') || promptEmail();
  var btn = input.closest('.upload-btn');
  if (btn) {{ btn.textContent = 'Uploading…'; btn.classList.add('uploading'); }}
  var fd = new FormData();
  fd.append('file', input.files[0]);
  fetch('/api/upload/' + source, {{
    method: 'POST', headers: {{'X-User-Email': email}}, body: fd
  }}).then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      if (d.ok) {{ location.reload(); }}
      else {{ alert('Upload failed: ' + (d.error || 'unknown')); if (btn) {{ btn.textContent = '὎4 Upload'; btn.classList.remove('uploading'); }} }}
    }}).catch(function(e) {{ alert('Upload error: ' + e); if (btn) {{ btn.textContent = '὎4 Upload'; btn.classList.remove('uploading'); }} }});
}}
function promptEmail() {{
  var e = prompt('Enter your SAP email (tracks who uploaded data):') || 'unknown';
  localStorage.setItem('user_email', e);
  document.getElementById('user-email-display').textContent = e.split('@')[0] || e;
  return e;
}}
function changeEmail() {{
  var cur = localStorage.getItem('user_email') || '';
  var e = prompt('Enter your SAP email:', cur);
  if (e) {{ localStorage.setItem('user_email', e); document.getElementById('user-email-display').textContent = e.split('@')[0] || e; }}
}}
function toggle(id) {{
  var el = document.getElementById(id); var tog = document.getElementById(id+'-tog');
  var hidden = el.style.display === 'none';
  el.style.display = hidden ? '' : 'none';
  tog.innerHTML = hidden ? '&#9660;' : '&#9654;';
}}
function filterText(cid, q) {{
  q = q.toLowerCase();
  document.getElementById(cid).querySelectorAll('tbody tr').forEach(function(r) {{
    if (r.classList.contains('row-hidden')) return;
    r.style.display = (!q || r.textContent.toLowerCase().includes(q)) ? '' : 'none';
  }});
}}
var priState = {{}};
function filterPri(cid, cls, btn) {{
  if (!priState[cid]) priState[cid] = {{}};
  priState[cid][cls] = !priState[cid][cls];
  btn.classList.toggle('active', priState[cid][cls]);
  var active = Object.keys(priState[cid]).filter(function(k) {{ return priState[cid][k]; }});
  document.getElementById(cid).querySelectorAll('tbody tr').forEach(function(r) {{
    if (r.classList.contains('row-hidden')) return;
    r.style.display = (!active.length || active.some(function(c) {{ return r.classList.contains('row-'+c); }})) ? '' : 'none';
  }});
}}
document.addEventListener('DOMContentLoaded', function() {{
  document.querySelectorAll('.ho-edit').forEach(function(el) {{
    var key = el.dataset.key;
    var val = sharedNotes[key] || '';
    var local = localStorage.getItem(key);
    if (local !== null) val = local;
    if (val) el.innerText = val;
  }});
  document.querySelectorAll('.lr-flag').forEach(function(el) {{
    var key = el.dataset.key;
    var val = sharedNotes[key] || localStorage.getItem(key);
    el.checked = val === '1';
  }});
  document.querySelectorAll('.move-select').forEach(function(sel) {{
    var tid = sel.dataset.ticket;
    var found = '';
    ['spc-current','spc-next','spc-lr','spc-updated'].forEach(function(s) {{
      if ((sharedNotes['move:' + s + ':' + tid] || '') === '1') found = s;
    }});
    sel.value = found;
  }});
  document.querySelectorAll('.hide-btn').forEach(function(btn) {{
    var val = localStorage.getItem(btn.dataset.key);
    if (val === '1') {{ var tr = btn.closest('tr'); tr.classList.add('row-hidden'); tr.style.display = 'none'; }}
  }});
  document.querySelectorAll('.show-hidden-btn').forEach(function(btn) {{
    var tbl = document.getElementById(btn.dataset.tbl);
    if (tbl) btn.textContent = 'Show hidden (' + tbl.querySelectorAll('tr.row-hidden').length + ')';
  }});
  document.querySelectorAll('.toggle-covered-btn').forEach(function(btn) {{
    var tbl = document.getElementById(btn.dataset.tbl);
    if (tbl) {{
      var uncovered = tbl.querySelectorAll('tbody tr:not(.row-covered):not(.row-hidden)').length;
      btn.textContent = 'Show only uncovered (' + uncovered + ' uncovered)';
    }}
  }});
  var infoVal = sharedNotes['info:notes'] || localStorage.getItem('info:notes') || '';
  if (infoVal) document.getElementById('info-area').innerText = infoVal;
  var serverUser = {json.dumps(current_user)};
  if (serverUser && serverUser !== 'unknown') {{
    localStorage.setItem('user_email', serverUser);
  }}
  var em = localStorage.getItem('user_email') || '—';
  document.getElementById('user-email-display').textContent = em === '—' ? '—' : (em.split('@')[0] || em);
}});
</script>
</body>
</html>"""
