import json
import time
import base64
import urllib.request
import urllib.parse

from app.services.shift import (
    detect_shift, get_shift_window, get_next_shift_window, get_previous_shift_window,
)
from app.services.xlsx_parser import (
    safe_col, filter_snow_by_shift, filter_spc_by_shift,
    filter_spc_longrunners, filter_spc_by_last_changed, get_flagged_ids,
)


def build_shift_message(store) -> str:
    ah, ar, _ = store.get_source("snow_alert")
    ch, cr, _ = store.get_source("snow_case")
    ih, ir, _ = store.get_source("snow_inc")
    sh, sr_all, _ = store.get_source("spc")
    ho = store.get_ho_status()

    shift_name = detect_shift()
    shift_label, shift_start, shift_end = get_shift_window(shift_name)
    next_label,  next_start,  next_end  = get_next_shift_window(shift_name)
    prev_label,  prev_start,  prev_end  = get_previous_shift_window(shift_name)

    ar_f = filter_snow_by_shift(ar, safe_col(ah, "Updated"), shift_start, shift_end,
                                 safe_col(ah, "Number"), get_flagged_ids(ho, "alerts"))
    cr_f = filter_snow_by_shift(cr, safe_col(ch, "Updated"), shift_start, shift_end,
                                 safe_col(ch, "Number"), get_flagged_ids(ho, "cases"))
    ir_f = filter_snow_by_shift(ir, safe_col(ih, "Updated"), shift_start, shift_end,
                                 safe_col(ih, "Number"), get_flagged_ids(ho, "inc"))

    s_subj = safe_col(sh, "Subject")
    s_link = safe_col(sh, "Ticket ID")
    s_lc   = safe_col(sh, "Last Changed At")
    lr_f   = get_flagged_ids(ho, "spc-lr")

    sr_cur = filter_spc_by_shift(sr_all, s_subj, shift_start, shift_end,
                                  s_link, get_flagged_ids(ho, "spc-current"))
    sr_nxt = filter_spc_by_shift(sr_all, s_subj, next_start, next_end,
                                  s_link, get_flagged_ids(ho, "spc-next"))
    sr_lr  = filter_spc_longrunners(sr_all, s_link, lr_f)
    sched  = {r[s_link] for r in sr_cur + sr_nxt if s_link < len(r) and r[s_link]} | lr_f
    sr_upd = filter_spc_by_last_changed(sr_all, s_lc, prev_start, prev_end,
                                         s_link, set(), exclude_ids=sched)

    total_spc = len(sr_cur) + len(sr_nxt) + len(sr_lr) + len(sr_upd)
    return (
        f"📊 Shift Dashboard ready — {shift_label}\n\n"
        f"🔔 Snow Alerts:    {len(ar_f)}\n"
        f"📋 Snow Cases:     {len(cr_f)}\n"
        f"🚨 Internal INCs:  {len(ir_f)}\n"
        f"🎫 SPC Tickets:    {total_spc} "
        f"(Current: {len(sr_cur)}, Next: {len(sr_nxt)}, "
        f"Longrunners: {len(sr_lr)}, Updated: {len(sr_upd)})"
    )


def _get_ans_token(oauth_url: str, client_id: str, client_secret: str) -> str:
    # VCAP_SERVICES provides the full token URL (may include ?grant_type=... query string)
    token_url = oauth_url.split("?")[0]
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        token_url,
        data=data,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]


def send_ans_event(message: str, ans_url: str, oauth_url: str,
                   client_id: str, client_secret: str) -> dict:
    token = _get_ans_token(oauth_url, client_id, client_secret)

    first_line = message.split("\n")[0]
    if " — " in first_line:
        subject = "Shift Dashboard — " + first_line.split(" — ", 1)[1]
    else:
        subject = "Shift Dashboard Notification"

    event = {
        "eventType": "ShiftHandoverNotification",
        "eventTimestamp": int(time.time()),
        "severity": "INFO",
        "category": "NOTIFICATION",
        "subject": subject,
        "body": message,
        "resource": {
            "resourceName": "shift-ho-dashboard",
            "resourceType": "application",
            "resourceInstance": "shift-handover",
        },
    }

    payload = json.dumps(event).encode()
    req = urllib.request.Request(
        f"{ans_url}/cf/producer/v1/resource-events",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return {"http_status": resp.status}
