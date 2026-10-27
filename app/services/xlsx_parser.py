import io
import re
import zipfile
import sys
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET

from app.services.shift import EET, parse_spc_subject_dt

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def safe_col(headers, name):
    return headers.index(name) if name in headers else 0


def col_letter_to_idx(letters):
    idx = 0
    for ch in letters.upper():
        idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return idx - 1


def parse_col(ref):
    m = re.match(r"([A-Za-z]+)", ref)
    return m.group(1).upper() if m else None


def excel_serial_to_str(serial):
    try:
        dt = datetime(1899, 12, 30) + timedelta(days=float(serial))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(serial)


def _open_zip(source):
    """Accept a file path (str/Path), bytes, or BytesIO."""
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    return zipfile.ZipFile(source)


def read_snow_xlsx(source):
    """Parse a Snow export (Alert/Case/Inc). Returns (headers, rows)."""
    try:
        with _open_zip(source) as zf:
            with zf.open("xl/worksheets/sheet1.xml") as f:
                root = ET.fromstring(f.read())
        all_rows = root.findall(".//x:row", NS)
        if not all_rows:
            return [], []

        headers = []
        for c in all_rows[0].findall("x:c", NS):
            is_el = c.find("x:is/x:t", NS)
            headers.append(is_el.text.strip() if is_el is not None else "")

        rows = []
        for row_el in all_rows[1:]:
            cells_by_col = {}
            for c in row_el.findall("x:c", NS):
                ref = c.get("r", "")
                col = parse_col(ref)
                if col is None:
                    continue
                t = c.get("t", "")
                if t == "inlineStr":
                    is_el = c.find("x:is/x:t", NS)
                    val = is_el.text.strip() if is_el is not None else ""
                else:
                    v_el = c.find("x:v", NS)
                    raw = v_el.text if v_el is not None else ""
                    try:
                        fval = float(raw)
                        val = excel_serial_to_str(raw) if fval > 40000 else raw
                    except (ValueError, TypeError):
                        val = raw or ""
                cells_by_col[col_letter_to_idx(col)] = val
            if cells_by_col:
                rows.append([cells_by_col.get(i, "") for i in range(len(headers))])
        return headers, rows
    except Exception as e:
        print(f"  Warning: read_snow_xlsx: {e}", file=sys.stderr)
        return [], []


def read_spc_xlsx(source):
    """Parse SPCReport.xlsx. Returns (headers, rows, meta)."""
    try:
        with _open_zip(source) as zf:
            col_names, start_col_idx = [], 1
            for name in zf.namelist():
                if "tables/" in name and name.endswith(".xml") and "tableSingleCells" not in name:
                    with zf.open(name) as f:
                        tbl = ET.fromstring(f.read())
                    col_names = [c.get("name", "") for c in tbl.findall(".//x:tableColumn", NS)]
                    tbl_ref = tbl.get("ref", "B5")
                    start_col_idx = col_letter_to_idx(re.match(r"([A-Za-z]+)", tbl_ref).group(1))
                    break

            with zf.open("xl/worksheets/sheet1.xml") as f:
                root = ET.fromstring(f.read())

        all_rows = root.findall(".//x:row", NS)

        meta = {}
        for row_el in all_rows:
            r_attr = row_el.get("r")
            if r_attr == "1":
                for c in row_el.findall("x:c", NS):
                    is_el = c.find("x:is/x:t", NS)
                    if is_el is not None:
                        meta["title"] = is_el.text.strip()
            elif r_attr == "3":
                vals = []
                for c in row_el.findall("x:c", NS):
                    t = c.get("t", "")
                    if t == "inlineStr":
                        is_el = c.find("x:is/x:t", NS)
                        vals.append(is_el.text.strip() if is_el is not None else "")
                    else:
                        v_el = c.find("x:v", NS)
                        vals.append(v_el.text if v_el is not None else "")
                for i, v in enumerate(vals):
                    if v == "Last Updated On:" and i + 1 < len(vals):
                        meta["last_updated"] = excel_serial_to_str(vals[i + 1])
                    if v == "Timezone:" and i + 1 < len(vals):
                        meta["timezone"] = vals[i + 1]

        data_rows = []
        past_header = False
        for row_el in all_rows:
            r_attr = row_el.get("r")
            if r_attr == "5":
                past_header = True
                continue
            if not past_header:
                continue

            cells_by_col = {}
            current_col = start_col_idx
            for c in row_el.findall("x:c", NS):
                col = parse_col(c.get("r", ""))
                if col is not None:
                    current_col = col_letter_to_idx(col)
                col_idx = current_col - start_col_idx
                t = c.get("t", "")
                if t == "inlineStr":
                    is_el = c.find("x:is/x:t", NS)
                    val = is_el.text.strip() if is_el is not None else ""
                else:
                    v_el = c.find("x:v", NS)
                    raw = v_el.text if v_el is not None else ""
                    try:
                        fval = float(raw)
                        val = excel_serial_to_str(raw) if fval > 40000 else raw
                    except (ValueError, TypeError):
                        val = raw or ""
                cells_by_col[col_idx] = val
                current_col += 1

            if cells_by_col:
                data_rows.append([cells_by_col.get(i, "") for i in range(len(col_names))])

        return col_names, data_rows, meta
    except Exception as e:
        print(f"  Warning: read_spc_xlsx: {e}", file=sys.stderr)
        return [], [], {}


def get_flagged_ids(ho_status, section_id):
    prefix = f"lr:{section_id}:"
    return {k[len(prefix):] for k, v in ho_status.items()
            if k.startswith(prefix) and str(v) == "1"}


def get_excluded_ids(ho_status, section_id):
    prefix = f"exclude:{section_id}:"
    return {k[len(prefix):] for k, v in ho_status.items()
            if k.startswith(prefix) and str(v) == "1"}


def get_section_overrides(ho_status: dict) -> dict:
    overrides = {"spc-current": set(), "spc-next": set(), "spc-tbc": set(), "spc-updated": set(), "spc-prev": set(), "cases-active": set(), "alerts-active": set(), "inc-active": set()}
    for key, val in ho_status.items():
        if key.startswith("move:") and str(val) == "1":
            parts = key.split(":", 2)
            if len(parts) == 3 and parts[1] in overrides:
                overrides[parts[1]].add(parts[2])
    return overrides


def apply_section_override(section_rows, all_rows, link_col_idx, override_ids, excluded=None):
    excluded = excluded or set()
    if not override_ids:
        return section_rows
    existing = {r[link_col_idx] for r in section_rows if link_col_idx < len(r)}
    extras = [r for r in all_rows
              if link_col_idx < len(r) and r[link_col_idx] in override_ids
              and r[link_col_idx] not in existing
              and r[link_col_idx] not in excluded]
    return section_rows + extras


def filter_snow_by_shift(rows, updated_col_idx, start_str, end_str, link_col_idx, flagged):
    out = []
    for row in rows:
        ticket = row[link_col_idx] if link_col_idx < len(row) else ""
        val    = row[updated_col_idx] if updated_col_idx < len(row) else ""
        if ticket in flagged or (val and start_str <= val < end_str):
            out.append(row)
    return out


def filter_snow_by_status(rows, state_col_idx, states, link_col_idx, flagged, excluded=None):
    excluded = excluded or set()
    states_lower = {s.lower() for s in states}
    out = []
    for row in rows:
        ticket = row[link_col_idx] if link_col_idx < len(row) else ""
        state  = (row[state_col_idx] if state_col_idx < len(row) else "").lower()
        if ticket in excluded:
            continue
        if ticket in flagged or state in states_lower:
            out.append(row)
    return out


def filter_spc_by_shift(rows, subject_col_idx, start_str, end_str, link_col_idx, flagged):
    start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M").replace(tzinfo=EET)
    end_dt   = datetime.strptime(end_str,   "%Y-%m-%d %H:%M").replace(tzinfo=EET) if end_str else None
    out = []
    for row in rows:
        ticket  = row[link_col_idx]    if link_col_idx    < len(row) else ""
        subject = row[subject_col_idx] if subject_col_idx < len(row) else ""
        if ticket in flagged:
            continue
        dt_utc = parse_spc_subject_dt(subject)
        if dt_utc:
            dt_eet = dt_utc.astimezone(EET)
            if start_dt <= dt_eet and (end_dt is None or dt_eet < end_dt):
                out.append(row)
    return out


def filter_spc_longrunners(rows, link_col_idx, flagged):
    return [r for r in rows
            if (r[link_col_idx] if link_col_idx < len(r) else "") in flagged]


def filter_spc_by_last_changed(rows, lc_col_idx, shift_start_str, shift_end_str,
                                link_col_idx, flagged, exclude_ids=None):
    exclude_ids = exclude_ids or set()
    start_dt = datetime.strptime(shift_start_str, "%Y-%m-%d %H:%M").replace(tzinfo=EET)
    end_dt   = datetime.strptime(shift_end_str,   "%Y-%m-%d %H:%M").replace(tzinfo=EET)
    out = []
    for row in rows:
        ticket = row[link_col_idx] if link_col_idx < len(row) else ""
        if ticket in flagged or ticket in exclude_ids:
            continue
        val = row[lc_col_idx] if lc_col_idx < len(row) else ""
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
            try:
                dt = datetime.strptime(str(val).strip()[:19], fmt).replace(tzinfo=timezone.utc)
                break
            except (ValueError, TypeError):
                pass
        if dt and start_dt <= dt.astimezone(EET) < end_dt:
            out.append(row)
    return out
