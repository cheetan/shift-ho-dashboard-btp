import os
from flask import Flask, request, jsonify


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

    from app.routes.health import bp as health_bp
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.api import bp as api_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp)

    @app.before_request
    def require_xsuaa_token():
        # /health is public; /api/upload/ uses its own API-key check
        if request.path == '/health' or request.path.startswith('/api/upload/') or request.path.startswith('/static/'):
            return
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized'}), 401
        token = auth[7:]
        try:
            import jwt
            from app.config import get_xsuaa_config
            xsuaa = get_xsuaa_config()
            if xsuaa.get('verificationkey'):
                jwt.decode(token, xsuaa['verificationkey'],
                           algorithms=['RS256'], options={'verify_aud': False})
            else:
                jwt.decode(token, options={'verify_signature': False})
        except Exception:
            return jsonify({'error': 'Unauthorized'}), 401

    return app
