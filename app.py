import logging
import os
import re
from datetime import timedelta, datetime

import requests
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

TORN_USER_BASIC_URL = "https://api.torn.com/user/"
ADMIN_TORN_ID = 2823859
MOD_TORN_IDS = {
    tid
    for tid in (
        int(x)
        for x in os.environ.get("MOD_TORN_IDS", "").split(",")
        if x.strip().isdigit()
    )
}

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    torn_user_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
    torn_name = db.Column(db.String(64), nullable=False)
    role_id = db.Column(db.Integer, nullable=False, default=1)  # 1=regular, 2=mod, 3=admin
    sent_xanax_total = db.Column(db.Integer, nullable=False, default=0)
    insurance_total = db.Column(db.Integer, nullable=False, default=0)
    api_key = db.Column(db.String(128), nullable=True)  # User's Torn API key for verification

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    coverage_type = db.Column(db.String(10), nullable=False)  # 'XAN' or 'EXTC'
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending, active, completed, cancelled
    
    # Payment details
    xanax_payment = db.Column(db.Integer, nullable=False)
    payment_verified = db.Column(db.Boolean, default=False)
    payment_verified_at = db.Column(db.DateTime, nullable=True)
    
    # Coverage details for XAN
    hours = db.Column(db.Integer, nullable=True)  # For XAN coverage
    xanax_reward = db.Column(db.Integer, nullable=True)
    
    # Coverage details for EXTC
    jumps = db.Column(db.Integer, nullable=True)  # For EXTC coverage
    edvds_reward = db.Column(db.Integer, nullable=True)
    ecstasy_reward = db.Column(db.Integer, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    activated_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    
    # Auto-detection flag
    auto_detected = db.Column(db.Boolean, default=False)
    
    # Relationships
    user = db.relationship('User', backref='orders')

class PricingConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    coverage_type = db.Column(db.String(10), nullable=False)  # 'XAN' or 'EXTC'
    duration = db.Column(db.Integer, nullable=False)  # hours for XAN, jumps for EXTC
    cost = db.Column(db.Integer, nullable=False)
    xanax_reward = db.Column(db.Integer, nullable=False)
    edvds_reward = db.Column(db.Integer, nullable=True)  # Only for EXTC
    ecstasy_reward = db.Column(db.Integer, nullable=True)  # Only for EXTC
    active = db.Column(db.Boolean, default=True)

class AutoVerifySettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, default=False)
    interval_minutes = db.Column(db.Integer, default=5)
    last_check = db.Column(db.DateTime, nullable=True)
    auto_delete_enabled = db.Column(db.Boolean, default=False)
    auto_delete_hours = db.Column(db.Integer, default=24)

class Overdose(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    coverage_type = db.Column(db.String(10), nullable=True)  # 'XAN' or 'EXTC'
    reported_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    confirmed = db.Column(db.Boolean, default=False)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    payout = db.Column(db.Integer, nullable=True)  # Primary payout amount given
    payout_details = db.Column(db.String(500), nullable=True)  # Full payout info (e.g., "100 Xanax, 50 eDVDs, 25 Ecstasy")
    notes = db.Column(db.String(500), nullable=True)
    
    # Individual payout amounts for EXTC
    payout_xanax = db.Column(db.Integer, nullable=True)  # Amount of xanax paid
    payout_edvds = db.Column(db.Integer, nullable=True)  # Amount of eDVDs paid (EXTC only)
    payout_ecstasy = db.Column(db.Integer, nullable=True)  # Amount of ecstasy paid (EXTC only)
    
    # Relationships
    user = db.relationship('User', backref='overdoses')

def create_app():
    app = Flask(__name__, instance_relative_config=True)

    # Quiet noisy HTTP request logs in production-ish runs
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.logger.setLevel(logging.WARNING)

    # SECURITY: Set secret key via env var in real deployments
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")

    # SQLite in instance/ folder (keeps repo clean)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(app.instance_path, "app.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # SECURITY: Session hardening (works best behind HTTPS in production)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # app.config["SESSION_COOKIE_SECURE"] = True  # enable when using HTTPS
    app.permanent_session_lifetime = timedelta(days=7)

    db.init_app(app)

    with app.app_context():
        db.create_all()

    def fetch_torn_basic(api_key: str) -> dict:
        # Small input sanity check; Torn keys are typically hex-like strings.
        # Don't over-restrict: just block obviously invalid input.
        if not api_key or len(api_key) < 8 or len(api_key) > 128:
            raise ValueError("API key format looks invalid.")

        if not re.fullmatch(r"[A-Za-z0-9]+", api_key):
            raise ValueError("API key should be alphanumeric.")

        # SECURITY: never log the key; keep request timeouts short
        params = {"selections": "basic", "key": api_key}
        r = requests.get(TORN_USER_BASIC_URL, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()

        # Torn API commonly returns {"error": {"code": ..., "error": "..."}}
        if isinstance(data, dict) and "error" in data:
            msg = data["error"].get("error", "Torn API error")
            raise ValueError(msg)

        return data

    from routes import register_routes

    register_routes(app, db, User, Order, PricingConfig, AutoVerifySettings, Overdose, fetch_torn_basic, ADMIN_TORN_ID, MOD_TORN_IDS)

    return app

app = create_app()

if __name__ == "__main__":
    # Local testing only
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False, use_reloader=False)
