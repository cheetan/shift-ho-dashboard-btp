import os
import json


def get_hana_config() -> dict:
    """Return HANA connection params. Explicit env vars take priority over VCAP_SERVICES."""
    if os.environ.get("HANA_HOST"):
        return {
            "host":     os.environ["HANA_HOST"],
            "port":     int(os.environ.get("HANA_PORT", "443")),
            "user":     os.environ.get("HANA_USER", ""),
            "password": os.environ.get("HANA_PASSWORD", ""),
        }

    # VCAP_SERVICES fallback — only when credentials include user+password
    vcap = os.environ.get("VCAP_SERVICES")
    if vcap:
        try:
            for svc_list in json.loads(vcap).values():
                for svc in svc_list:
                    c = svc.get("credentials", {})
                    user = c.get("user") or c.get("username", "")
                    password = c.get("password", "")
                    if "host" in c and "port" in c and user and password:
                        return {
                            "host":     c["host"],
                            "port":     int(c["port"]),
                            "user":     user,
                            "password": password,
                        }
        except Exception:
            pass

    return {"host": "", "port": 443, "user": "", "password": ""}


def get_xsuaa_config() -> dict:
    """Extract XSUAA credentials from VCAP_SERVICES (set when xsuaa service is bound in CF)."""
    vcap = os.environ.get("VCAP_SERVICES")
    if vcap:
        try:
            for svc in json.loads(vcap).get("xsuaa", []):
                c = svc.get("credentials", {})
                if c.get("clientid"):
                    return {
                        "clientid":        c.get("clientid", ""),
                        "clientsecret":    c.get("clientsecret", ""),
                        "url":             c.get("url", ""),
                        "verificationkey": c.get("verificationkey", ""),
                    }
        except Exception:
            pass
    return {}


USE_MEMORY_STORE: bool = os.environ.get("USE_MEMORY_STORE", "false").lower() == "true"
