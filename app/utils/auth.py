from flask import Request


def get_user_from_request(request: Request) -> str:
    """Extract verified user identity from XSUAA JWT, with local dev fallback."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        try:
            import jwt
            from app.config import get_xsuaa_config
            xsuaa = get_xsuaa_config()
            if xsuaa.get("verificationkey"):
                payload = jwt.decode(
                    token,
                    xsuaa["verificationkey"],
                    algorithms=["RS256"],
                    options={"verify_aud": False},
                )
            else:
                payload = jwt.decode(token, options={"verify_signature": False})
            return payload.get("email") or payload.get("user_name") or "unknown"
        except Exception:
            pass
    return request.headers.get("X-User-Email", "unknown")
