"""LumiSignals Bot SaaS — multi-user cloud service."""

import json
import os
import logging
from datetime import datetime, timezone, timedelta

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
        lumitrade_api_key = db.Column(db.String(255))

        # Bot settings (legacy globals — kept for backward compat)
        trading_timeframe = db.Column(db.String(10), default="1d")
        min_score = db.Column(db.Integer, default=50)
        min_risk_reward = db.Column(db.Float, default=1.5)
        stock_atr_multiplier = db.Column(db.Float, default=0.5)
        dry_run = db.Column(db.Boolean, default=True)
        dry_run_stocks = db.Column(db.Boolean, default=True)
        bot_active = db.Column(db.Boolean, default=False)

        # Per-model strategy settings
        scalp_min_score = db.Column(db.Integer, default=50)
        scalp_min_rr = db.Column(db.Float, default=1.5)
        scalp_atr_multiplier = db.Column(db.Float, default=0.5)
        intraday_min_score = db.Column(db.Integer, default=50)
        intraday_min_rr = db.Column(db.Float, default=1.5)
        intraday_atr_multiplier = db.Column(db.Float, default=0.5)
        swing_min_score = db.Column(db.Integer, default=50)
        swing_min_rr = db.Column(db.Float, default=1.5)
        swing_atr_multiplier = db.Column(db.Float, default=0.5)

        # Per-model risk settings: mode is "percent" or "fixed" (dollar amount)
        scalp_risk_mode = db.Column(db.String(10), default="percent")
        scalp_risk_value = db.Column(db.Float, default=0.25)
        scalp_daily_budget = db.Column(db.Float, default=0.0)
        intraday_risk_mode = db.Column(db.String(10), default="percent")
        intraday_risk_value = db.Column(db.Float, default=0.5)
        intraday_daily_budget = db.Column(db.Float, default=0.0)
        swing_risk_mode = db.Column(db.String(10), default="percent")
        swing_risk_value = db.Column(db.Float, default=1.0)
        swing_daily_budget = db.Column(db.Float, default=0.0)

        # Options position sizing (IB)
        options_max_risk_per_spread = db.Column(db.Float, default=200.0)
        options_max_contracts = db.Column(db.Integer, default=5)
        options_max_total_risk = db.Column(db.Float, default=2000.0)
        options_spread_width = db.Column(db.Float, default=5.0)
        options_min_credit_pct = db.Column(db.Float, default=25.0)
        options_max_spreads = db.Column(db.Integer, default=10)
        options_auto_trade = db.Column(db.Boolean, default=False)
        options_auto_spread_type = db.Column(db.String(10), default="credit")  # credit, debit, both
        options_trigger_tf = db.Column(db.String(10), default="4h")  # trigger TF for stock options
        options_min_verdict = db.Column(db.String(10), default="good")  # good, fair

        # Options exit rules
        credit_tp_pct = db.Column(db.Float, default=50.0)     # Take profit at X% of credit collected
        credit_sl_pct = db.Column(db.Float, default=100.0)    # Stop loss at X% of credit (2x = 100%)
        debit_tp_pct = db.Column(db.Float, default=75.0)      # Take profit at X% gain
        debit_sl_pct = db.Column(db.Float, default=50.0)      # Stop loss at X% loss
        options_time_stop_dte = db.Column(db.Integer, default=7)  # Close at X DTE

        # Futures settings
        futures_stop_loss = db.Column(db.Float, default=25.0)  # Stop loss in dollars per contract

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
            current_user.massive_api_key = request.form.get("massive_api_key", "").strip()
            current_user.lumitrade_api_key = request.form.get("lumitrade_api_key", "").strip()
            current_user.schwab_client_id = request.form.get("schwab_client_id", "").strip()
            current_user.schwab_client_secret = request.form.get("schwab_client_secret", "").strip()
            current_user.dry_run = "dry_run" in request.form
            current_user.dry_run_stocks = "dry_run_stocks" in request.form
            current_user.stock_atr_multiplier = float(request.form.get("stock_atr_multiplier", 0.5))

            # Per-model strategy settings
            for model in ["scalp", "intraday", "swing"]:
                setattr(current_user, f"{model}_min_score", int(request.form.get(f"{model}_min_score", 50) or 50))
                setattr(current_user, f"{model}_min_rr", float(request.form.get(f"{model}_min_rr", 1.5) or 1.5))
                setattr(current_user, f"{model}_atr_multiplier", float(request.form.get(f"{model}_atr_multiplier", 0.5) or 0.5))

            # Per-model risk settings
            for model in ["scalp", "intraday", "swing"]:
                mode = request.form.get(f"{model}_risk_mode", "percent")
                setattr(current_user, f"{model}_risk_mode", mode)
                setattr(current_user, f"{model}_risk_value", float(request.form.get(f"{model}_risk_value", 0) or 0))
                setattr(current_user, f"{model}_daily_budget", float(request.form.get(f"{model}_daily_budget", 0) or 0))

            # Options position sizing
            current_user.options_max_risk_per_spread = float(request.form.get("options_max_risk_per_spread", 200) or 200)
            current_user.options_max_contracts = int(request.form.get("options_max_contracts", 5) or 5)
            current_user.options_max_total_risk = float(request.form.get("options_max_total_risk", 2000) or 2000)
            current_user.options_spread_width = float(request.form.get("options_spread_width", 5) or 5)
            current_user.options_min_credit_pct = float(request.form.get("options_min_credit_pct", 25) or 25)
            current_user.options_max_spreads = int(request.form.get("options_max_spreads", 10) or 10)
            current_user.options_auto_trade = "options_auto_trade" in request.form
            current_user.options_auto_spread_type = request.form.get("options_auto_spread_type", "credit")
            current_user.options_trigger_tf = request.form.get("options_trigger_tf", "4h")
            current_user.options_min_verdict = request.form.get("options_min_verdict", "good")

            # Options exit rules
            current_user.credit_tp_pct = float(request.form.get("credit_tp_pct", 50) or 50)
            current_user.credit_sl_pct = float(request.form.get("credit_sl_pct", 100) or 100)
            current_user.debit_tp_pct = float(request.form.get("debit_tp_pct", 75) or 75)
            current_user.debit_sl_pct = float(request.form.get("debit_sl_pct", 50) or 50)
            current_user.options_time_stop_dte = int(request.form.get("options_time_stop_dte", 7) or 7)

            # Futures settings
            current_user.futures_stop_loss = float(request.form.get("futures_stop_loss", 25) or 25)

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

    @app.route("/strategy")
    @login_required
    def strategy():
        return render_template("strategy.html", user=current_user)

    @app.route("/compare")
    @login_required
    def compare():
        return render_template("compare.html", user=current_user)

    @app.route("/scanner")
    @login_required
    def scanner():
        return render_template("scanner.html", user=current_user)

    # -----------------------------------------------------------------------
    # IB CPAPI Auth Proxy — proxies the IB login page through the dashboard
    # -----------------------------------------------------------------------

    @app.route("/ib-auth")
    @login_required
    def ib_auth_page():
        """Show IB re-authentication page."""
        return render_template("ib_auth.html", user=current_user)

    @app.route("/ib-auth/proxy/<path:path>", methods=["GET", "POST", "PUT"])
    @login_required
    def ib_auth_proxy(path):
        """Proxy requests to the CPAPI gateway for authentication."""
        import requests as _req
        cpapi_url = os.environ.get("CPAPI_BASE_URL", "https://localhost:5000/v1/api").replace("/v1/api", "")
        target = f"{cpapi_url}/{path}"
        try:
            if request.method == "POST":
                resp = _req.post(target, json=request.get_json(silent=True),
                                data=request.form if not request.is_json else None,
                                headers={"Content-Type": request.content_type or "application/json"},
                                verify=False, timeout=15, allow_redirects=False)
            elif request.method == "PUT":
                resp = _req.put(target, json=request.get_json(silent=True),
                               verify=False, timeout=15, allow_redirects=False)
            else:
                resp = _req.get(target, params=request.args, verify=False, timeout=15,
                               allow_redirects=False)

            # Handle redirects — rewrite CPAPI URLs to our proxy
            if resp.status_code in (301, 302, 303, 307):
                location = resp.headers.get("Location", "")
                if location.startswith("https://localhost:5000"):
                    location = location.replace("https://localhost:5000", "/ib-auth/proxy")
                return redirect(location)

            # Rewrite response content — replace CPAPI URLs with proxy URLs
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" in content_type or "javascript" in content_type:
                body = resp.text.replace("https://localhost:5000", "/ib-auth/proxy")
                return body, resp.status_code, {"Content-Type": content_type}

            return resp.content, resp.status_code, {"Content-Type": content_type}
        except Exception as e:
            return jsonify({"error": f"CPAPI proxy error: {e}"}), 502

    @app.route("/ib-auth/status")
    @login_required
    def ib_auth_status():
        """Check IB CPAPI authentication status."""
        import requests as _req
        cpapi_url = os.environ.get("CPAPI_BASE_URL", "https://localhost:5000/v1/api")
        try:
            resp = _req.post(f"{cpapi_url}/iserver/auth/status", verify=False, timeout=5)
            return jsonify(resp.json())
        except Exception as e:
            return jsonify({"authenticated": False, "error": str(e)})

    # -----------------------------------------------------------------------
    # API endpoints
    # -----------------------------------------------------------------------

    @app.route("/api/status")
    @login_required
    def api_status():
        running = current_user.bot_active

        # Check Schwab token status
        schwab_status = {"connected": False, "expires_in_days": None, "warning": None}
        for tf in [f"/opt/lumisignals/schwab_tokens_user_{current_user.id}.json", "/opt/lumisignals/schwab_tokens.json"]:
            if not os.path.exists(tf):
                continue
            try:
                with open(tf) as f:
                    tokens = json.load(f)
                saved_at = tokens.get("saved_at", "")
                token_expiry = tokens.get("token_expiry", 0)
                if saved_at:
                    import re
                    # Extract just the datetime part, ignore timezone for simplicity
                    match = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", saved_at)
                    if match:
                        saved_dt = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                        refresh_expiry = saved_dt + timedelta(days=7)
                        now = datetime.now(timezone.utc)
                        days_left = (refresh_expiry - now).days
                        schwab_status["connected"] = days_left > 0
                        schwab_status["expires_in_days"] = max(days_left, 0)
                        if days_left <= 0:
                            schwab_status["connected"] = False
                            schwab_status["warning"] = "Schwab token expired — run schwab_auth.py to re-authorize"
                        elif days_left <= 2:
                            schwab_status["warning"] = f"Schwab token expires in {days_left} day{'s' if days_left != 1 else ''} — re-authorize soon"
                        break
                elif token_expiry > 0:
                    schwab_status["connected"] = True
                    schwab_status["expires_in_days"] = 7
                    break
            except Exception as e:
                logger.error("Schwab token check error for %s: %s", tf, e)

        # Check IB sync status
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        ib_data = rdb.get(f"ibkr:data:{current_user.id}")
        ib_connected = bool(ib_data)

        return jsonify({
            "user": current_user.email,
            "plan": current_user.plan,
            "bot_active": running,
            "dry_run": current_user.dry_run,
            "has_oanda": bool(current_user.oanda_api_key),
            "has_schwab": bool(current_user.schwab_client_id) or schwab_status.get("connected", False),
            "has_massive": bool(current_user.massive_api_key),
            "schwab": schwab_status,
            "ib_connected": ib_connected,
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
        """Analyze options using all available sources: Schwab, Polygon, IB."""
        import redis as _redis
        import uuid
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

        zone_type = request.args.get("zone_type", "supply")
        zone_price = float(request.args.get("zone_price", 0))
        current_price = float(request.args.get("current_price", 0))

        response = {"ticker": ticker, "sources": []}

        # --- Source 1: Schwab (instant if authorized) ---
        try:
            from lumisignals.schwab_client import SchwabAuth, SchwabMarketData
            from lumisignals.options_analyzer import analyze_spreads_at_zone, format_spread_for_display
            schwab_id = current_user.schwab_client_id or os.environ.get("SCHWAB_CLIENT_ID", "")
            schwab_secret = current_user.schwab_client_secret or os.environ.get("SCHWAB_CLIENT_SECRET", "")
            auth = SchwabAuth(
                client_id=schwab_id,
                client_secret=schwab_secret,
                token_file=f"/opt/lumisignals/schwab_tokens_user_{current_user.id}.json",
            )
            # Fall back to shared token file
            if not auth.get_valid_token():
                auth = SchwabAuth(
                    client_id=schwab_id,
                    client_secret=schwab_secret,
                    token_file="/opt/lumisignals/schwab_tokens.json",
                )
            if auth.get_valid_token():
                md = SchwabMarketData(auth)
                schwab_result = analyze_spreads_at_zone(md, ticker, zone_type, zone_price, current_price)
                response["sources"].append({
                    "name": "Schwab",
                    "credit_spread": format_spread_for_display(schwab_result["credit_spread"]),
                    "debit_spread": format_spread_for_display(schwab_result["debit_spread"]),
                    "error": schwab_result.get("error"),
                })
        except Exception as e:
            logger.debug("Schwab options: %s", e)

        # --- Source 2: Polygon (run inline — fast with snapshot endpoint) ---
        massive_key = current_user.massive_api_key or os.environ.get("MASSIVE_API_KEY", "")
        if massive_key:
            try:
                from lumisignals.polygon_options import analyze_spreads_polygon
                # Calculate ATR for optimal debit placement
                poly_atr = 0
                try:
                    from datetime import timedelta as _td
                    end_d = datetime.now().strftime("%Y-%m-%d")
                    start_d = (datetime.now() - _td(days=25)).strftime("%Y-%m-%d")
                    atr_r = requests.get(
                        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start_d}/{end_d}",
                        params={"apiKey": massive_key, "adjusted": "true", "sort": "asc", "limit": 20},
                        timeout=10,
                    )
                    if atr_r.ok:
                        atr_bars = atr_r.json().get("results", [])
                        if len(atr_bars) >= 2:
                            atr_trs = []
                            for ai in range(1, len(atr_bars)):
                                ah, al, apc = atr_bars[ai]["h"], atr_bars[ai]["l"], atr_bars[ai-1]["c"]
                                atr_trs.append(max(ah - al, abs(ah - apc), abs(al - apc)))
                            poly_atr = sum(atr_trs[-14:]) / min(len(atr_trs), 14)
                except Exception:
                    pass
                poly_result = analyze_spreads_polygon(massive_key, ticker, zone_type, zone_price, current_price,
                                                     atr=poly_atr)
                response["sources"].append({
                    "name": "Polygon",
                    "credit_spread": poly_result.get("credit_spread"),
                    "debit_spread": poly_result.get("debit_spread"),
                    "error": poly_result.get("error"),
                })
            except Exception as e:
                logger.debug("Polygon options: %s", e)

        # --- Source 3: IB (cached or queue) ---
        ib_cached = rdb.get(f"ibkr:analyze:result:{ticker}")
        if ib_cached:
            ib_data = json.loads(ib_cached)
            response["sources"].append({
                "name": "IB" + (" (Friday close)" if ib_data.get("data_mode") == "friday_close" else " (live)" if ib_data.get("data_mode") == "live" else ""),
                "credit_spread": ib_data.get("credit_spread"),
                "debit_spread": ib_data.get("debit_spread"),
                "error": ib_data.get("error"),
            })
        else:
            request_id = str(uuid.uuid4())[:8]
            rdb.setex(f"ibkr:analyze:request:{request_id}", 120, json.dumps({
                "request_id": request_id, "ticker": ticker,
                "zone_type": zone_type, "zone_price": zone_price,
                "current_price": current_price,
            }))

        # Use first available source for primary display
        for src in response["sources"]:
            if src.get("credit_spread") or src.get("debit_spread"):
                response["credit_spread"] = src.get("credit_spread")
                response["debit_spread"] = src.get("debit_spread")
                response["data_mode"] = src.get("name", "")
                break

        if not response.get("credit_spread") and not response.get("debit_spread") and not response["sources"]:
            response["status"] = "pending"
            response["message"] = "Analyzing — results will appear shortly"

        return jsonify(response)

    @app.route("/api/ibkr/analyze/status/<request_id>")
    @login_required
    def api_options_status(request_id):
        """Check if an analyze result is ready."""
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        result = rdb.get(f"ibkr:analyze:done:{request_id}")
        if result:
            return jsonify(json.loads(result))
        return jsonify({"status": "pending"})

    @app.route("/api/ibkr/analyze/pending")
    def api_ibkr_analyze_pending():
        """Return pending analyze requests for the sync script."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        requests_list = []
        for key in rdb.scan_iter("ibkr:analyze:request:*"):
            raw = rdb.get(key)
            if raw:
                req = json.loads(raw)
                requests_list.append(req)
                rdb.delete(key)  # consume the request
        return jsonify({"requests": requests_list})

    @app.route("/api/ibkr/analyze/result", methods=["POST"])
    def api_ibkr_analyze_result():
        """Receive analyze result from sync script."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        data = request.get_json()
        request_id = data.get("request_id", "")
        ticker = data.get("ticker", "")
        # Store by request_id (for polling) and by ticker (for cache)
        result_json = json.dumps(data)
        rdb.setex(f"ibkr:analyze:done:{request_id}", 300, result_json)
        rdb.setex(f"ibkr:analyze:result:{ticker}", 300, result_json)
        return jsonify({"status": "ok"})

    @app.route("/api/ibkr/order", methods=["POST"])
    @login_required
    def api_ibkr_place_order():
        """Queue a spread order for the IB sync script to place."""
        import redis as _redis
        import uuid
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        data = request.get_json()
        order_id = str(uuid.uuid4())[:8]
        data["order_id"] = order_id
        data["user_id"] = current_user.id
        data["status"] = "queued"
        data["queued_at"] = datetime.now(timezone.utc).isoformat()
        rdb.setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(data))  # 24h TTL
        return jsonify({"status": "queued", "order_id": order_id})

    @app.route("/api/ibkr/orders/pending")
    def api_ibkr_orders_pending():
        """Return orders with status 'queued' for the sync script to place."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        orders = []
        for key in rdb.scan_iter("ibkr:order:*"):
            raw = rdb.get(key)
            if raw:
                order = json.loads(raw)
                if order.get("status") == "queued":
                    orders.append(order)
                    # Mark as "placing" so we don't pick it up again
                    order["status"] = "placing"
                    rdb.setex(key, 86400, json.dumps(order))
        return jsonify({"orders": orders})

    @app.route("/api/ibkr/orders/all")
    @login_required
    def api_ibkr_orders_all():
        """Return all options orders for the Trades page. Auto-cleans old cancelled/failed orders."""
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        orders = []
        now = datetime.now(timezone.utc)
        for key in rdb.scan_iter("ibkr:order:*"):
            key_str = key.decode() if isinstance(key, bytes) else key
            if ":details:" in key_str:
                continue
            raw = rdb.get(key)
            if not raw:
                continue
            order = json.loads(raw)
            # Auto-clean: remove cancelled/failed orders older than 24h
            status = order.get("status", "")
            if status in ("cancelled", "Cancelled", "failed", "FAILED"):
                queued_at = order.get("queued_at", "")
                if queued_at:
                    try:
                        order_time = datetime.fromisoformat(queued_at.replace("Z", "+00:00"))
                        if (now - order_time).total_seconds() > 86400:
                            rdb.delete(key)
                            continue
                    except Exception:
                        pass
            if not order.get("ticker") and not order.get("symbol"):
                continue
            if order.get("user_id") == current_user.id:
                orders.append(order)
        # Sort: queued/placing first, then by time
        status_order = {"queued": 0, "placing": 1, "submitted": 2, "filled": 3, "failed": 4, "cancelled": 5}
        orders.sort(key=lambda o: (status_order.get(o.get("status", ""), 9), o.get("order_id", "")))
        return jsonify({"orders": orders})

    @app.route("/api/ibkr/order/update", methods=["POST"])
    def api_ibkr_order_update():
        """Update order status (called by sync script after placing)."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        data = request.get_json()
        order_id = data.get("order_id", "")
        # Find and update the order
        for key in rdb.scan_iter("ibkr:order:*"):
            raw = rdb.get(key)
            if raw:
                order = json.loads(raw)
                if order.get("order_id") == order_id:
                    order.update(data)
                    rdb.setex(key, 86400, json.dumps(order))
                    # Also store by IB order ID and permId for enrichment
                    ib_order_id = data.get("ib_order_id")
                    perm_id = data.get("perm_id")
                    if ib_order_id:
                        rdb.setex(f"ibkr:order:details:{ib_order_id}", 604800, json.dumps(order))
                    if perm_id:
                        rdb.setex(f"ibkr:order:perm:{perm_id}", 604800, json.dumps(order))
                    return jsonify({"status": "ok"})
        # Not found — create new entry (e.g. futures_entry_{permId} tracking)
        new_key = f"ibkr:order:{order_id}"
        rdb.setex(new_key, 604800, json.dumps(data))  # 7-day TTL
        perm_id = data.get("perm_id")
        if perm_id:
            rdb.setex(f"ibkr:order:perm:{perm_id}", 604800, json.dumps(data))
        return jsonify({"status": "created"})

    @app.route("/api/ibkr/exit-rules")
    def api_ibkr_exit_rules():
        """Return options exit rules for the sync script."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        # Get first active user's exit rules (single-user for now)
        from sqlalchemy import text
        result = db.session.execute(text(
            "SELECT credit_tp_pct, credit_sl_pct, debit_tp_pct, debit_sl_pct, options_time_stop_dte, futures_stop_loss "
            "FROM users WHERE bot_active = true LIMIT 1"
        ))
        row = result.fetchone()
        if row:
            return jsonify({
                "credit_tp_pct": row[0] or 50,
                "credit_sl_pct": row[1] or 100,
                "debit_tp_pct": row[2] or 75,
                "debit_sl_pct": row[3] or 50,
                "time_stop_dte": row[4] or 7,
                "futures_stop_loss": row[5] or 25,
            })
        return jsonify({})

    @app.route("/api/ibkr/closed-trade", methods=["POST"])
    def api_ibkr_closed_trade():
        """Record a closed options trade."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        import uuid
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        data = request.get_json()
        trade_id = str(uuid.uuid4())[:8]
        data["trade_id"] = trade_id
        # Store with 30-day TTL
        rdb.setex(f"ibkr:closed:{trade_id}", 2592000, json.dumps(data))
        return jsonify({"status": "ok", "trade_id": trade_id})

    @app.route("/api/ibkr/closed-trades")
    @login_required
    def api_ibkr_closed_trades():
        """Return all closed options trades."""
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        trades = []
        for key in rdb.scan_iter("ibkr:closed:*"):
            raw = rdb.get(key)
            if raw:
                trades.append(json.loads(raw))
        # Sort by closed_at descending
        trades.sort(key=lambda t: t.get("closed_at", ""), reverse=True)
        return jsonify({"trades": trades})

    @app.route("/api/ibkr/signal-lookup/<ticker>")
    def api_ibkr_signal_lookup(ticker):
        """Look up signal metadata for a ticker from the signal log."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        try:
            from lumisignals.signal_log import SignalLog
            sig_log = SignalLog(path="/opt/lumisignals/signal_log_user_1.json")
            entries = sig_log.get_all()
            # Find most recent signal for this ticker
            best = None
            best_time = ""
            for key, sig in entries.items():
                if not isinstance(sig, dict):
                    continue
                sym = sig.get("symbol", "").replace("_", "").upper()
                if sym == ticker.upper():
                    logged = sig.get("logged_at", "")
                    if logged > best_time:
                        best = sig
                        best_time = logged
            if best:
                return jsonify({
                    "model": best.get("model", ""),
                    "strategy": best.get("strategy", ""),
                    "trigger_pattern": best.get("trigger_pattern", ""),
                    "bias_score": best.get("bias_score", 0),
                    "zone_type": best.get("zone_type", ""),
                    "zone_timeframe": best.get("zone_timeframe", ""),
                    "zone_price": best.get("zone_price", 0),
                    "signal_action": best.get("action", ""),
                    "entry": best.get("entry", 0),
                    "risk_reward": best.get("risk_reward", 0),
                })
        except Exception as e:
            logger.debug("Signal lookup error: %s", e)
        return jsonify({})

    @app.route("/api/ibkr/futures-entry/<ticker>/<direction>")
    def api_ibkr_futures_entry(ticker, direction):
        """Find the most recent futures entry for a ticker + direction."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        best = None
        best_time = ""
        for key in rdb.scan_iter("ibkr:order:*"):
            raw = rdb.get(key)
            if not raw:
                continue
            entry = json.loads(raw)
            # Match by order_id containing "futures_entry" OR by type+status
            oid = entry.get("order_id", "")
            if "futures_entry" not in oid:
                continue
            if entry.get("ticker") == ticker and entry.get("direction") == direction and entry.get("status") == "entry":
                opened = entry.get("opened_at", "")
                if opened > best_time:
                    best = entry
                    best_time = opened
        if best:
            return jsonify(best)
        return jsonify({})

    @app.route("/api/ibkr/order/search")
    def api_ibkr_order_search():
        """Search stored order details by ticker + strikes."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        ticker = request.args.get("ticker", "")
        sell_strike = float(request.args.get("sell_strike", 0))
        buy_strike = float(request.args.get("buy_strike", 0))
        # Search through all stored order details
        for key in rdb.scan_iter("ibkr:order:details:*"):
            raw = rdb.get(key)
            if raw:
                details = json.loads(raw)
                if (details.get("ticker") == ticker and
                    abs(float(details.get("sell_strike", 0)) - sell_strike) < 0.01 and
                    abs(float(details.get("buy_strike", 0)) - buy_strike) < 0.01):
                    return jsonify(details)
        # Also search done orders
        for key in rdb.scan_iter("ibkr:order:done:*"):
            raw = rdb.get(key)
            if raw:
                details = json.loads(raw)
                if (details.get("ticker") == ticker and
                    abs(float(details.get("sell_strike", 0)) - sell_strike) < 0.01 and
                    abs(float(details.get("buy_strike", 0)) - buy_strike) < 0.01):
                    return jsonify(details)
        return jsonify({})

    @app.route("/api/ibkr/order/details/<ib_order_id>")
    def api_ibkr_order_details(ib_order_id):
        """Look up stored order details by IB order ID."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        stored = rdb.get(f"ibkr:order:details:{ib_order_id}")
        if stored:
            return jsonify(json.loads(stored))
        return jsonify({})

    @app.route("/api/account/balance")
    @login_required
    def api_account_balance():
        """Get account balance and NAV from Oanda."""
        if not current_user.oanda_api_key:
            return jsonify({"error": "No Oanda credentials"}), 400
        try:
            from lumisignals.oanda_client import OandaClient
            client = OandaClient(
                account_id=current_user.oanda_account_id,
                api_key=current_user.oanda_api_key,
                environment=current_user.oanda_environment or "practice",
            )
            acct = client.get_account().get("account", {})
            return jsonify({
                "balance": float(acct.get("balance", 0)),
                "unrealized_pl": float(acct.get("unrealizedPL", 0)),
                "nav": float(acct.get("NAV", 0)),
                "margin_used": float(acct.get("marginUsed", 0)),
                "currency": acct.get("currency", "USD"),
            })
        except Exception as e:
            logger.error("Account balance error: %s", e)
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

    @app.route("/api/ibkr/sync", methods=["POST"])
    def api_ibkr_sync():
        """Receive IB data from local sync script and store in Redis."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        data = request.get_json()
        # Add sync timestamp so the UI can show data freshness
        from datetime import datetime as _dt, timezone as _tz
        data["last_synced"] = _dt.now(_tz.utc).isoformat()
        # Store with 60-second TTL (sync script pushes every 10s)
        rdb.setex("ibkr:data:1", 60, json.dumps(data))
        return jsonify({"status": "ok"})

    @app.route("/api/ibkr/trades")
    @login_required
    def api_ibkr_trades():
        """Get IB positions, spreads, and account data from Redis."""
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = rdb.get(f"ibkr:data:{current_user.id}")
        if not raw:
            return jsonify({"connected": False, "account": {}, "positions": [], "spreads": [], "open_orders": [], "filled_orders": []})
        data = json.loads(raw)
        data["connected"] = True
        return jsonify(data)

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

    # -----------------------------------------------------------------------
    # SNR / Trend Comparison API
    # -----------------------------------------------------------------------

    @app.route("/api/tv/levels", methods=["POST"])
    def api_tv_levels():
        """Store TradingView untouched levels + ADX trend from Pine Script webhook.

        Expected JSON:
        {
            "ticker": "SPY",
            "key": "lumisignals2026",
            "levels": {
                "M": {"supply": 600.5, "demand": 510.2},
                "W": {"supply": 575.0, "demand": 530.8},
                "D": {"supply": 560.0, "demand": 540.3},
                "4H": {"supply": 555.0, "demand": 542.1}
            },
            "trends": {
                "M": {"dir": "UP", "adx": 28.5},
                "W": {"dir": "DOWN", "adx": 22.1},
                "D": {"dir": "DOWN", "adx": 31.0},
                "4H": {"dir": "UP", "adx": 18.4},
                "1H": {"dir": "DOWN", "adx": 27.3}
            }
        }
        """
        import redis as _redis
        data = request.get_json(silent=True) or {}
        if data.get("key") != os.environ.get("TV_WEBHOOK_KEY", "lumisignals2026"):
            return jsonify({"error": "Invalid key"}), 403
        ticker = data.get("ticker", "").upper().strip()
        if not ticker:
            return jsonify({"error": "Missing ticker"}), 400
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        from datetime import datetime as _dt, timezone as _tz
        store = {
            "ticker": ticker,
            "levels": data.get("levels", {}),
            "trends": data.get("trends", {}),
            "updated_at": _dt.now(_tz.utc).isoformat(),
        }
        rdb.setex(f"tv:levels:{ticker}", 86400, json.dumps(store))
        return jsonify({"status": "ok", "ticker": ticker})

    @app.route("/api/compare/levels")
    @login_required
    def api_compare_levels():
        """Fetch LumiTrade SNR levels + TradingView levels side by side for comparison."""
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

        tickers = request.args.get("tickers", "SPY,TSLA,NVDA").upper().split(",")
        tickers = [t.strip() for t in tickers if t.strip()]

        snr_base_url = "https://app.lumitrade.ai/api/v1"
        snr_api_key = current_user.lumitrade_api_key or os.environ.get("LUMITRADE_API_KEY", "")

        # SNR Frequency API interval names → display labels
        interval_to_tf = {"3mo": "Q", "1mo": "M", "1w": "W", "1d": "D", "4h": "4H", "1h": "1H"}
        snr_intervals = ["3mo", "1mo", "1w", "1d", "4h", "1h"]
        # Trade-builder for trend data
        freq_to_tf = {"quarterly": "Q", "monthly": "M", "weekly": "W", "daily": "D", "fourhour": "4H", "hourly": "1H"}
        frequencies = ["quarterly", "monthly", "weekly", "daily", "fourhour", "hourly"]

        results = []
        for ticker in tickers:
            item = {"ticker": ticker, "lumitrade": {}, "tradingview": {}, "tv_trends": {}, "lt_trends": {}, "tv_updated": ""}

            if snr_api_key:
                import requests as _requests
                session = _requests.Session()
                session.headers["Authorization"] = f"Bearer {snr_api_key}"

                # --- SNR Frequency API (matches LumiTrade chart exactly) ---
                try:
                    resp = session.get(
                        f"{snr_base_url}/partners/technical-analysis/snr/frequency/",
                        params={"ticker": ticker, "intervals": ",".join(snr_intervals),
                                "type": "stock", "days": 256},
                        timeout=15,
                    )
                    if resp.status_code == 200:
                        snr_data = resp.json().get("data", resp.json())
                        for interval, tf_label in interval_to_tf.items():
                            tf_data = snr_data.get(interval, {})
                            if isinstance(tf_data, dict):
                                item["lumitrade"][tf_label] = {
                                    "supply": tf_data.get("resistance_price"),
                                    "demand": tf_data.get("support_price"),
                                }
                except Exception as e:
                    item["lumitrade"]["error"] = str(e)

                # --- Trade-builder for trend/direction data ---
                try:
                    resp2 = session.get(
                        f"{snr_base_url}/partners/technical-analysis/trade-builder-setup",
                        params={"ticker": ticker, "period": 14, "market": "stock",
                                "frequency": ",".join(frequencies)},
                        timeout=15,
                    )
                    if resp2.status_code == 200:
                        tb_data = resp2.json().get("data", resp2.json())
                        for freq, tv_tf in freq_to_tf.items():
                            tf_data = tb_data.get(freq, {})
                            if isinstance(tf_data, dict):
                                pos = tf_data.get("position", "")
                                if pos:
                                    dir_str = "UP" if pos in ("positive", "long") else "DOWN" if pos in ("negative", "short") else "SIDE"
                                    item["lt_trends"][tv_tf] = dir_str
                except Exception:
                    pass
            else:
                item["lumitrade"]["error"] = "No LumiTrade API key configured"

            # --- TradingView levels from Redis ---
            tv_raw = rdb.get(f"tv:levels:{ticker}")
            if tv_raw:
                tv_data = json.loads(tv_raw)
                item["tradingview"] = tv_data.get("levels", {})
                item["tv_trends"] = tv_data.get("trends", {})
                item["tv_updated"] = tv_data.get("updated_at", "")

            results.append(item)

        return jsonify({"tickers": results})

    # -----------------------------------------------------------------------
    # Scanner — scan stocks for proximity to untouched S/R levels
    # -----------------------------------------------------------------------

    @app.route("/api/scanner/scan")
    @login_required
    def api_scanner_scan():
        """Scan universe of stocks for setups near untouched levels."""
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

        # Check cache (scan is expensive, cache for 5 min)
        cached = rdb.get("scanner:results")
        if cached and not request.args.get("refresh"):
            return jsonify(json.loads(cached))

        massive_key = os.environ.get("MASSIVE_API_KEY", "")
        if not massive_key:
            return jsonify({"error": "No Massive API key configured"}), 400

        from lumisignals.massive_client import MassiveClient, CORE_TICKERS, SWING_TICKERS, TICKER_NAMES
        from lumisignals.untouched_levels import scan_universe, scan_ticker, TIMEFRAMES

        client = MassiveClient(massive_key)
        proximity = float(request.args.get("proximity", 2.0))
        tickers = request.args.get("tickers", "").upper().split(",")
        tickers = [t.strip() for t in tickers if t.strip()]

        # Swing scan: full expanded list on M/W only
        # Intraday/Scalp scan: core tickers on D/4H/1H
        swing_list = SWING_TICKERS if not tickers else tickers
        core_list = CORE_TICKERS[:30] if not tickers else tickers
        if tickers:
            swing_list = tickers
            core_list = tickers

        all_setups = []

        # Scan swing tickers (M/W only — faster, broader)
        for ticker in swing_list:
            try:
                candles_1d = client.get_candles(ticker, "1d", 2)
                if not candles_1d:
                    continue
                price = candles_1d[-1].close
                levels = scan_ticker(client, ticker, price, ["1mo", "1w"])
                for tf_label, lvl in levels.items():
                    for level_type, level_price in [("D1", lvl.demand1), ("D2", lvl.demand2), ("S1", lvl.supply1), ("S2", lvl.supply2)]:
                        if level_price is None or level_price == 0:
                            continue
                        dist_pct = (price - level_price) / price * 100
                        is_demand = level_type.startswith("D")
                        if is_demand and not (0 < dist_pct <= proximity):
                            continue
                        if not is_demand and not (-proximity <= dist_pct < 0):
                            continue
                        direction = "BUY" if is_demand else "SELL"
                        score = 1 if (direction == "BUY" and lvl.trend == "UP") or (direction == "SELL" and lvl.trend == "DOWN") else 0
                        if lvl.adx >= 25:
                            score += 1
                        all_setups.append({
                            "ticker": ticker, "name": TICKER_NAMES.get(ticker, ""), "price": round(price, 2), "level": round(level_price, 2),
                            "level_type": level_type, "tf": tf_label,
                            "tf_name": {"M": "Monthly", "W": "Weekly"}.get(tf_label, tf_label),
                            "distance_pct": round(dist_pct, 2), "direction": direction,
                            "trend": lvl.trend, "adx": lvl.adx, "score": score,
                        })
            except Exception:
                continue

        # Scan core tickers (D/4H/1H — intraday + scalp)
        for ticker in core_list:
            try:
                candles_1d = client.get_candles(ticker, "1d", 2)
                if not candles_1d:
                    continue
                price = candles_1d[-1].close
                levels = scan_ticker(client, ticker, price, ["1d", "4h", "1h"])
                for tf_label, lvl in levels.items():
                    for level_type, level_price in [("D1", lvl.demand1), ("D2", lvl.demand2), ("S1", lvl.supply1), ("S2", lvl.supply2)]:
                        if level_price is None or level_price == 0:
                            continue
                        dist_pct = (price - level_price) / price * 100
                        is_demand = level_type.startswith("D")
                        if is_demand and not (0 < dist_pct <= proximity):
                            continue
                        if not is_demand and not (-proximity <= dist_pct < 0):
                            continue
                        direction = "BUY" if is_demand else "SELL"
                        score = 1 if (direction == "BUY" and lvl.trend == "UP") or (direction == "SELL" and lvl.trend == "DOWN") else 0
                        if lvl.adx >= 25:
                            score += 1
                        all_setups.append({
                            "ticker": ticker, "name": TICKER_NAMES.get(ticker, ""), "price": round(price, 2), "level": round(level_price, 2),
                            "level_type": level_type, "tf": tf_label,
                            "tf_name": {"D": "Daily", "4H": "4-Hour", "1H": "Hourly"}.get(tf_label, tf_label),
                            "distance_pct": round(dist_pct, 2), "direction": direction,
                            "trend": lvl.trend, "adx": lvl.adx, "score": score,
                        })
            except Exception:
                continue

        # Sort by score desc, TF desc, distance
        tf_rank = {"M": 5, "W": 4, "D": 3, "4H": 2, "1H": 1}
        all_setups.sort(key=lambda s: (-s["score"], -tf_rank.get(s["tf"], 0), abs(s["distance_pct"])))
        setups = all_setups
        tickers_scanned = len(set(swing_list) | set(core_list))

        result = {"setups": setups, "tickers_scanned": tickers_scanned, "proximity_pct": proximity}
        rdb.setex("scanner:results", 300, json.dumps(result))
        return jsonify(result)

    @app.route("/api/scanner/ticker/<ticker>")
    @login_required
    def api_scanner_ticker(ticker):
        """Get detailed untouched levels for a single ticker."""
        massive_key = os.environ.get("MASSIVE_API_KEY", "")
        if not massive_key:
            return jsonify({"error": "No Massive API key configured"}), 400

        from lumisignals.massive_client import MassiveClient
        from lumisignals.untouched_levels import scan_ticker

        client = MassiveClient(massive_key)
        candles = client.get_candles(ticker.upper(), "1d", 2)
        price = candles[-1].close if candles else 0

        levels = scan_ticker(client, ticker.upper(), price)
        data = {
            "ticker": ticker.upper(),
            "price": round(price, 2),
            "levels": {k: {
                "supply1": v.supply1, "supply2": v.supply2,
                "demand1": v.demand1, "demand2": v.demand2,
                "trend": v.trend, "adx": v.adx,
            } for k, v in levels.items()},
        }
        return jsonify(data)

    @app.route("/api/scanner/swing-auto")
    @login_required
    def api_scanner_swing_auto():
        """Trigger a swing auto-scan with candle confirmation."""
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        massive_key = os.environ.get("MASSIVE_API_KEY", "")
        if not massive_key:
            return jsonify({"error": "No Massive API key"}), 400

        dry_run = request.args.get("dry_run", "false").lower() == "true"

        from lumisignals.massive_client import MassiveClient
        from lumisignals.swing_scanner import run_swing_scan

        client = MassiveClient(massive_key)
        triggered = run_swing_scan(client, rdb, massive_key, dry_run=dry_run)

        return jsonify({
            "status": "ok",
            "triggered": len(triggered),
            "setups": triggered,
            "dry_run": dry_run,
        })

    # -----------------------------------------------------------------------
    # TradingView Webhook — receives alerts, places 0DTE options trades
    # -----------------------------------------------------------------------

    @app.route("/api/webhook/tradingview", methods=["POST"])
    def api_tradingview_webhook():
        """Receive a TradingView alert and queue a 0DTE options trade.

        Expected JSON payload:
        {
            "ticker": "SPY",           # required
            "direction": "BUY",        # BUY or SELL
            "strategy": "vwap_bounce", # strategy name for logging
            "key": "lumisignals2026",  # simple auth key
            "spread_type": "credit",   # credit, debit, or both (default: credit)
            "contracts": 2,            # override contract count (optional)
            "dte": 0,                  # 0 for 0DTE, or specific days (optional)
            "tp_pct": 35,              # take profit % (optional, default by dte)
            "sl_pct": 25,              # stop loss % (optional, default by dte)
            "time_stop_min": 15        # close after X minutes (optional)
        }
        """
        import redis as _redis
        import uuid

        data = request.get_json(silent=True) or {}

        # Simple auth
        webhook_key = data.get("key", "")
        if webhook_key != os.environ.get("TV_WEBHOOK_KEY", "lumisignals2026"):
            return jsonify({"error": "Invalid key"}), 403

        ticker = data.get("ticker", "").upper().strip()
        direction = data.get("direction", "").upper().strip()
        strategy = data.get("strategy", "tradingview")

        # ─── LEVELS SYNC PATH — store TV levels for comparison dashboard ───
        if strategy == "tv_levels_sync":
            rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
            from datetime import datetime as _dt, timezone as _tz
            store = {
                "ticker": ticker,
                "levels": data.get("levels", {}),
                "trends": data.get("trends", {}),
                "updated_at": _dt.now(_tz.utc).isoformat(),
            }
            rdb.setex(f"tv:levels:{ticker}", 86400, json.dumps(store))
            return jsonify({"status": "ok", "action": "levels_sync", "ticker": ticker})

        trade_type = data.get("type", "options")  # "options" or "futures"
        spread_pref = data.get("spread_type", "credit")
        override_contracts = data.get("contracts", 1)
        dte = data.get("dte", 0)

        # ─── FUTURES PATH ───
        if trade_type == "futures":
            rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Handle close signals
            close_reason = data.get("reason", "")

            if direction in ("CLOSE_LONG", "CLOSE_SHORT"):
                order_id = str(uuid.uuid4())[:8]
                order = {
                    "order_id": order_id,
                    "queued_at": datetime.now(timezone.utc).isoformat(),
                    "user_id": 1,
                    "ticker": ticker,
                    "type": "futures",
                    "direction": direction,
                    "strategy": strategy,
                    "reason": close_reason,
                    "contracts": int(override_contracts or 1),
                    "status": "queued",
                }
                rdb.setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))
                return jsonify({"status": "queued", "action": direction, "ticker": ticker})

            # Deduplication for entry signals
            dedup_key = f"tv:futures:{ticker}:{strategy}:{direction}:{today}"
            if rdb.get(dedup_key):
                return jsonify({"status": "skipped", "reason": f"{ticker} {strategy} already traded"})

            order_id = str(uuid.uuid4())[:8]
            order = {
                "order_id": order_id,
                "queued_at": datetime.now(timezone.utc).isoformat(),
                "user_id": 1,
                "ticker": ticker,
                "type": "futures",
                "direction": direction,
                "strategy": strategy,
                "contracts": int(override_contracts or 1),
                "status": "queued",
                "auto": True,
                "model": "0dte",
                "signal_action": direction,
            }
            rdb.setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))
            rdb.setex(dedup_key, 180, "1")  # 3-min dedup for futures (covers one 2-min candle)

            # Alert
            try:
                from lumisignals.alerts import send_alert, AlertType
                alert_pass = os.environ.get("ALERT_EMAIL_PASSWORD", "")
                if alert_pass:
                    send_alert(AlertType.TRADE_OPENED, f"Futures: {direction} {ticker} — {strategy}",
                               f"TradingView 2n20 signal", details={"Ticker": ticker, "Direction": direction, "Strategy": strategy, "Contracts": str(override_contracts or 1)},
                               smtp_pass=alert_pass)
            except Exception:
                pass

            return jsonify({"status": "queued", "ticker": ticker, "direction": direction, "strategy": strategy, "contracts": override_contracts or 1})

        # ─── OPTIONS PATH ───
        # 0DTE exit rules: tighter than swing
        if dte == 0:
            default_tp = 35
            default_sl = 25
            default_time_stop = 15  # minutes
        else:
            default_tp = 50
            default_sl = 50
            default_time_stop = 0  # use DTE-based time stop
        tp_pct = data.get("tp_pct", default_tp)
        sl_pct = data.get("sl_pct", default_sl)
        time_stop_min = data.get("time_stop_min", default_time_stop)

        if not ticker:
            return jsonify({"error": "Missing ticker"}), 400
        if direction not in ("BUY", "SELL"):
            return jsonify({"error": "Direction must be BUY or SELL"}), 400

        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

        # Deduplication — don't place same ticker + strategy + direction twice today
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dedup_key = f"tv:traded:{ticker}:{strategy}:{direction}:{today}"
        if rdb.get(dedup_key):
            return jsonify({"status": "skipped", "reason": f"{ticker} {strategy} already traded today"})

        # Determine zone type from direction
        zone_type = "demand" if direction == "BUY" else "supply"

        # TV level price (S1/D1) — used as zone reference for strike selection
        level_price = data.get("level_price", 0)
        level_tf = data.get("level_tf", "")
        trade_duration = data.get("trade_duration", "")
        score = data.get("score", 0)

        # Get current price from Polygon
        try:
            import requests as req
            massive_key = os.environ.get("MASSIVE_API_KEY", "")
            if massive_key:
                resp = req.get(f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev",
                              params={"apiKey": massive_key}, timeout=10)
                if resp.ok:
                    results = resp.json().get("results", [])
                    current_price = results[0]["c"] if results else 0
                else:
                    current_price = 0
            else:
                current_price = 0
        except Exception:
            current_price = 0

        if not current_price:
            return jsonify({"error": f"Could not get price for {ticker}"}), 400

        # Use TV level price as the zone reference if provided, otherwise current price
        zone_price = float(level_price) if level_price else current_price

        # DTE based on trade duration
        if trade_duration == "5min":
            dte = 0
        elif trade_duration == "hourly":
            dte = data.get("dte", 1)
        elif trade_duration == "daily":
            dte = data.get("dte", 7)
        else:
            dte = data.get("dte", 0)

        # Analyze options spread — use zone_price (S1/D1 level) as reference
        try:
            from lumisignals.polygon_options import analyze_spreads_polygon

            if dte == 0:
                min_dte_val, max_dte_val = 0, 1
            else:
                min_dte_val, max_dte_val = max(0, dte - 1), dte + 2

            # Get ATR for optimal debit placement
            atr_value = 0
            try:
                import requests as _req
                # Get last 15 daily bars to calculate 14-period ATR
                from datetime import datetime as _dt2, timedelta as _td2
                end = _dt2.now().strftime("%Y-%m-%d")
                start = (_dt2.now() - _td2(days=25)).strftime("%Y-%m-%d")
                atr_resp = _req.get(
                    f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
                    params={"apiKey": massive_key, "adjusted": "true", "sort": "asc", "limit": 20},
                    timeout=10,
                )
                if atr_resp.ok:
                    bars = atr_resp.json().get("results", [])
                    if len(bars) >= 2:
                        trs = []
                        for i in range(1, len(bars)):
                            h, l, pc = bars[i]["h"], bars[i]["l"], bars[i-1]["c"]
                            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
                        atr_value = sum(trs[-14:]) / min(len(trs), 14)
            except Exception:
                pass

            result = analyze_spreads_polygon(
                massive_key, ticker, zone_type, current_price, zone_price,
                max_risk_per_spread=500, preferred_width=5.0,
                min_dte=min_dte_val, max_dte=max_dte_val,
                atr=atr_value, score=int(score),
            )
        except Exception as e:
            return jsonify({"error": f"Analysis failed: {e}"}), 500

        # Pick the spread based on preference
        credit = result.get("credit_spread")
        debit = result.get("debit_spread")
        spreads_to_queue = []

        if spread_pref in ("credit", "both") and credit and credit.get("verdict") in ("GOOD", "FAIR"):
            spreads_to_queue.append(("credit", credit))
        if spread_pref in ("debit", "both") and debit and debit.get("verdict") in ("GOOD", "FAIR"):
            spreads_to_queue.append(("debit", debit))

        if not spreads_to_queue:
            return jsonify({
                "status": "no_trade",
                "reason": "No spread met GOOD/FAIR threshold",
                "credit_verdict": credit.get("verdict") if credit else "none",
                "debit_verdict": debit.get("verdict") if debit else "none",
            })

        # Size and queue orders
        from lumisignals.options_sizing import OptionsRiskConfig, calculate_spread_contracts

        # Get user settings (use first active user for now)
        try:
            from sqlalchemy import text
            row = db.session.execute(text(
                "SELECT options_max_risk_per_spread, options_max_contracts, options_max_total_risk, "
                "options_spread_width, options_min_credit_pct, options_max_spreads FROM users WHERE bot_active = true LIMIT 1"
            )).fetchone()
            if row:
                risk_config = OptionsRiskConfig(
                    max_risk_per_spread=float(row[0] or 500),
                    max_contracts=int(row[1] or 5),
                    max_total_risk=float(row[2] or 2000),
                    spread_width=float(row[3] or 5),
                    min_credit_pct=float(row[4] or 25),
                    max_spreads=int(row[5] or 10),
                )
            else:
                risk_config = OptionsRiskConfig()
        except Exception:
            risk_config = OptionsRiskConfig()

        queued = []
        for spread_kind, spread in spreads_to_queue:
            is_credit = spread["net_credit"] > 0
            premium = spread["net_credit"] if is_credit else spread["net_debit"]
            width = spread["width"]

            sizing = calculate_spread_contracts(
                spread_width=width, credit_or_debit=premium,
                is_credit=is_credit, risk_config=risk_config,
            )

            contracts = override_contracts or sizing.get("contracts", 0)
            if contracts <= 0:
                continue

            order_id = str(uuid.uuid4())[:8]
            order = {
                "order_id": order_id,
                "queued_at": datetime.now(timezone.utc).isoformat(),
                "user_id": 1,  # single user for now
                "ticker": ticker,
                "spread_type": spread["type"],
                "buy_strike": spread["long_strike"],
                "sell_strike": spread["short_strike"],
                "right": "C" if "Call" in spread["option_type"] else "P",
                "expiration": spread["expiration"],
                "quantity": contracts,
                "limit_price": premium,
                "is_credit": is_credit,
                "width": width,
                "max_risk": sizing.get("total_risk", 0),
                "max_profit": sizing.get("max_profit", 0),
                "risk_reward": spread["risk_reward"],
                "verdict": spread["verdict"],
                "status": "queued",
                "auto": True,
                "model": "0dte",
                "strategy": strategy,
                "zone_type": zone_type,
                "zone_price": zone_price,
                "trigger_pattern": f"TV: {strategy} @ {level_tf} {'D1' if zone_type == 'demand' else 'S1'}",
                "bias_score": score,
                "zone_timeframe": level_tf or f"0DTE ({dte}d)",
                "signal_action": direction,
                "signal_entry": current_price,
                "level_price": zone_price,
                "level_tf": level_tf,
                "trade_duration": trade_duration,
                "tp_pct": tp_pct,
                "sl_pct": sl_pct,
                "time_stop_min": time_stop_min,
            }
            rdb.setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))
            queued.append(f"{spread['type']} {contracts}x @ ${premium:.2f}")

        # Mark as traded today
        if queued:
            rdb.setex(dedup_key, 86400, "1")

            # Send email alert
            try:
                from lumisignals.alerts import send_alert, AlertType
                alert_pass = os.environ.get("ALERT_EMAIL_PASSWORD", "")
                if alert_pass:
                    send_alert(
                        AlertType.TRADE_OPENED,
                        f"TV Signal: {direction} {ticker} — {strategy}",
                        f"TradingView webhook triggered 0DTE options trade",
                        details={
                            "Ticker": ticker,
                            "Direction": direction,
                            "Strategy": strategy,
                            "Orders": ", ".join(queued),
                            "Price": f"${current_price:.2f}",
                        },
                        smtp_pass=alert_pass,
                    )
            except Exception:
                pass

        return jsonify({
            "status": "queued" if queued else "no_trade",
            "ticker": ticker,
            "direction": direction,
            "strategy": strategy,
            "orders": queued,
            "price": current_price,
        })

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=8000, debug=True)
