import os
import json


def get_hana_config() -> dict:
    """Return HANA connection params from VCAP_SERVICES (CF) or env vars (local dev)."""
    vcap = os.environ.get("VCAP_SERVICES")
    if vcap:
        try:
            for svc_list in json.loads(vcap).values():
                for svc in svc_list:
                    c = svc.get("credentials", {})
                    if "host" in c and "port" in c:
                        return {
                            "host":     c["host"],
                            "port":     int(c["port"]),
                            "user":     c.get("user") or c.get("username", ""),
                            "password": c.get("password", ""),
                        }
        except Exception:
            pass

    return {
        "host":     os.environ.get("HANA_HOST", ""),
        "port":     int(os.environ.get("HANA_PORT", "443")),
        "user":     os.environ.get("HANA_USER", ""),
        "password": os.environ.get("HANA_PASSWORD", ""),
    }


USE_MEMORY_STORE: bool = os.environ.get("USE_MEMORY_STORE", "false").lower() == "true"
