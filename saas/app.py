"""LumiSignals Bot SaaS — multi-user cloud service."""

import json
import os
import logging
from datetime import datetime, timezone

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

db = SQLAlchemy()
login_manager = LoginManager()
logger = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "d083f48c4e0973cfc6175749a6e4e1ee9659aeb295c1bd73d861c9977bcd151c")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False  # Set True when HTTPS only
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL",
        "postgresql://lumisignals:LumiBot2026@localhost/lumisignals_db",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login"

    # No cache
    @app.after_request
    def add_no_cache(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    # -----------------------------------------------------------------------
    # Models
    # -----------------------------------------------------------------------

    class User(UserMixin, db.Model):
        __tablename__ = "users"
        id = db.Column(db.Integer, primary_key=True)
        email = db.Column(db.String(255), unique=True, nullable=False)
        password_hash = db.Column(db.String(255), nullable=False)
        plan = db.Column(db.String(50), default="free")  # free, basic, pro, premium
        stripe_customer_id = db.Column(db.String(255))
        stripe_subscription_id = db.Column(db.String(255))
        created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

        # Broker credentials (encrypted in production)
        oanda_account_id = db.Column(db.String(255))
        oanda_api_key = db.Column(db.String(255))
        oanda_environment = db.Column(db.String(50), default="practice")
        schwab_client_id = db.Column(db.String(255))
        schwab_client_secret = db.Column(db.String(255))
        schwab_access_token = db.Column(db.Text)
        schwab_refresh_token = db.Column(db.Text)
        massive_api_key = db.Column(db.String(255))

        # Bot settings
        trading_timeframe = db.Column(db.String(10), default="1d")
        min_score = db.Column(db.Integer, default=50)
        min_risk_reward = db.Column(db.Float, default=1.5)
        stock_atr_multiplier = db.Column(db.Float, default=0.5)
        dry_run = db.Column(db.Boolean, default=True)
        bot_active = db.Column(db.Boolean, default=False)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Create tables
    with app.app_context():
        db.create_all()

    # -----------------------------------------------------------------------
    # Auth routes
    # -----------------------------------------------------------------------

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            if not email or not password:
                flash("Email and password required", "error")
                return render_template("signup.html")

            if len(password) < 8:
                flash("Password must be at least 8 characters", "error")
                return render_template("signup.html")

            if User.query.filter_by(email=email).first():
                flash("Email already registered", "error")
                return render_template("signup.html")

            user = User(
                email=email,
                password_hash=generate_password_hash(password),
                plan="free",
            )
            db.session.add(user)
            db.session.commit()
            login_user(user)
            return redirect(url_for("setup"))

        return render_template("signup.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = User.query.filter_by(email=email).first()

            if user and check_password_hash(user.password_hash, password):
                login_user(user)
                return redirect(url_for("dashboard"))
            flash("Invalid email or password", "error")

        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    # -----------------------------------------------------------------------
    # Setup — broker credentials
    # -----------------------------------------------------------------------

    @app.route("/setup", methods=["GET", "POST"])
    @login_required
    def setup():
        if request.method == "POST":
            current_user.oanda_account_id = request.form.get("oanda_account_id", "").strip()
            current_user.oanda_api_key = request.form.get("oanda_api_key", "").strip()
            current_user.oanda_environment = request.form.get("oanda_environment", "practice")
            current_user.trading_timeframe = request.form.get("trading_timeframe", "1d")
            current_user.min_score = int(request.form.get("min_score", 50))
            current_user.min_risk_reward = float(request.form.get("min_risk_reward", 1.5))
            current_user.stock_atr_multiplier = float(request.form.get("stock_atr_multiplier", 0.5))
            current_user.dry_run = "dry_run" in request.form
            db.session.commit()
            flash("Settings saved", "success")
            return redirect(url_for("dashboard"))

        return render_template("setup.html", user=current_user)

    # -----------------------------------------------------------------------
    # Dashboard
    # -----------------------------------------------------------------------

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html", user=current_user)

    @app.route("/watchlist")
    @login_required
    def watchlist():
        return render_template("watchlist.html", user=current_user)

    @app.route("/trades")
    @login_required
    def trades():
        return render_template("trades.html", user=current_user)

    # -----------------------------------------------------------------------
    # API endpoints
    # -----------------------------------------------------------------------

    @app.route("/api/status")
    @login_required
    def api_status():
        running = current_user.bot_active
        return jsonify({
            "user": current_user.email,
            "plan": current_user.plan,
            "bot_active": running,
            "dry_run": current_user.dry_run,
            "has_oanda": bool(current_user.oanda_api_key),
            "has_schwab": bool(current_user.schwab_client_id),
            "trading_timeframe": current_user.trading_timeframe,
        })

    @app.route("/api/bot/start", methods=["POST"])
    @login_required
    def api_start_bot():
        if not current_user.oanda_api_key:
            return jsonify({"error": "Connect your Oanda account first"}), 400

        from .worker import start_bot_for_user
        success = start_bot_for_user(current_user)
        if success:
            current_user.bot_active = True
            db.session.commit()
        return jsonify({"success": success, "message": "Bot started" if success else "Failed to start"})

    @app.route("/api/bot/stop", methods=["POST"])
    @login_required
    def api_stop_bot():
        from .worker import stop_bot_for_user
        stop_bot_for_user(current_user.id)
        current_user.bot_active = False
        db.session.commit()
        return jsonify({"success": True, "message": "Bot stopped"})

    @app.route("/api/watchlist")
    @login_required
    def api_watchlist():
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

        result = {}
        for model in ["scalp", "intraday", "swing"]:
            raw = rdb.get(f"watchlist:{current_user.id}:{model}")
            zones = json.loads(raw) if raw else []
            # Tag each zone with its model
            for z in zones:
                z["model"] = model
            stocks = [z for z in zones if z.get("is_stock") and not z.get("instrument", "").startswith("X:")]
            crypto = [z for z in zones if z.get("instrument", "").startswith("X:")]
            forex = [z for z in zones if not z.get("is_stock")]
            result[model] = {"stocks": stocks, "crypto": crypto, "forex": forex, "total": len(zones)}

        return jsonify(result)

    @app.route("/api/options/<ticker>")
    @login_required
    def api_options(ticker):
        zone_type = request.args.get("zone_type", "supply")
        zone_price = float(request.args.get("zone_price", 0))
        current_price = float(request.args.get("current_price", 0))
        try:
            from lumisignals.schwab_client import SchwabAuth, SchwabMarketData
            from lumisignals.options_analyzer import analyze_spreads_at_zone, format_spread_for_display
            auth = SchwabAuth(
                client_id=os.environ.get("SCHWAB_CLIENT_ID", ""),
                client_secret=os.environ.get("SCHWAB_CLIENT_SECRET", ""),
                token_file="/opt/lumisignals/schwab_tokens.json",
            )
            if not auth.get_valid_token():
                return jsonify({"error": "Schwab not authorized — run schwab_auth.py on server"}), 401
            md = SchwabMarketData(auth)
            result = analyze_spreads_at_zone(md, ticker, zone_type, zone_price, current_price)
            return jsonify({
                "ticker": ticker,
                "credit_spread": format_spread_for_display(result["credit_spread"]),
                "debit_spread": format_spread_for_display(result["debit_spread"]),
                "error": result.get("error"),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/oanda/trades")
    @login_required
    def api_oanda_trades():
        """Get open trades, pending orders, and closed trades from Oanda."""
        if not current_user.oanda_api_key:
            return jsonify({"error": "No Oanda credentials"}), 400
        try:
            from lumisignals.oanda_client import OandaClient
            from lumisignals.trade_tracker import get_open_trades, get_pending_orders, get_closed_trades, get_performance_stats
            from lumisignals.signal_log import SignalLog

            client = OandaClient(
                account_id=current_user.oanda_account_id,
                api_key=current_user.oanda_api_key,
                environment=current_user.oanda_environment or "practice",
            )

            # Use the user's signal log for enrichment
            sig_log_path = f"/opt/lumisignals/signal_log_user_{current_user.id}.json"
            from lumisignals.signal_log import _log, get_signal_log
            # Temporarily override the global signal log
            import lumisignals.signal_log as _sl
            old_log = _sl._log
            _sl._log = SignalLog(path=sig_log_path)

            open_trades = get_open_trades(client)
            pending = get_pending_orders(client)
            closed = get_closed_trades(client, count=50)
            stats = get_performance_stats(closed)

            # Restore
            _sl._log = old_log

            return jsonify({
                "open": open_trades,
                "pending": pending,
                "closed": closed,
                "stats": stats,
            })
        except Exception as e:
            logger.error("Oanda trades error: %s", e)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/log")
    @login_required
    def api_log():
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = rdb.get(f"botlog:{current_user.id}")
        entries = json.loads(raw) if raw else []
        return jsonify({"entries": entries})

    # -----------------------------------------------------------------------
    # Health check
    # -----------------------------------------------------------------------

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "service": "lumisignals-bot"})

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=8000, debug=True)
