"""LumiSignals Bot SaaS — multi-user cloud service."""

import json
import os
import logging
from datetime import datetime, timezone, timedelta

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, make_response
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
        futures_contracts = db.Column(db.Integer, default=1)   # N contracts per entry; exits flatten actual position

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
            current_user.futures_contracts = max(1, int(request.form.get("futures_contracts", 1) or 1))

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

    @app.route("/api/watchlist/zones")
    def api_watchlist_zones():
        """Return active HTF watchlist zones for mobile app."""
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

        result = []
        for model in ["scalp", "intraday", "swing"]:
            raw = rdb.get(f"watchlist:1:{model}")
            if not raw:
                continue
            zones = json.loads(raw)
            for z in zones:
                instrument = z.get("instrument", "")
                zone_price = z.get("zone_price", 0)
                zone_type = z.get("zone_type", "")
                zone_tf = z.get("zone_timeframe", "")
                status = z.get("status", "watching")
                bias_score = z.get("bias_score", 0)
                trends = z.get("trends", {})
                trade_dir = z.get("trade_direction", "")

                # Calculate distance from current price (if available in zone data)
                atr = z.get("atr", 0)

                result.append({
                    "instrument": instrument,
                    "model": model,
                    "zone_type": zone_type,
                    "zone_timeframe": zone_tf,
                    "zone_price": round(zone_price, 5),
                    "status": status,
                    "bias_score": bias_score,
                    "trade_direction": trade_dir,
                    "trends": trends,
                    "atr": round(atr, 5) if atr else 0,
                })

        # Supplemental always-on zones for key indices/commodities. Mirrors the
        # bot's real scan structure (model-aware zone_tfs, trend_tfs, ATR) so
        # the mobile cards look identical to forex zones — and stays visible
        # outside market hours when the bot's stock scan is gated off.
        MODEL_ZONE_TFS = {
            "scalp":    ["15m", "1h"],
            "intraday": ["1d", "1w"],
            "swing":    ["1w", "1mo"],
        }
        MODEL_TREND_TFS = {
            "scalp":    [("5m", "5M"), ("15m", "15M"), ("1h", "1H")],
            "intraday": [("1h", "1H"), ("1d", "Daily"), ("1w", "Weekly")],
            "swing":    [("1d", "Daily"), ("1w", "Weekly"), ("1mo", "Monthly")],
        }
        MODEL_TRIGGER_TF = {"scalp": "5m", "intraday": "1h", "swing": "1d"}

        def _compute_trends(massive, tkr, model):
            """ADX direction on each of the model's trend TFs."""
            trends = {}
            for tf, label in MODEL_TREND_TFS[model]:
                try:
                    count = 30 if tf in ("1mo", "1w") else (50 if tf in ("1d", "1h") else 80)
                    candles = massive.get_candles(tkr, tf, count)
                    if not candles or len(candles) < 16:
                        continue
                    direction, _ = calculate_adx_direction(candles, period=14)
                    trends[label] = "bullish" if direction == "UP" else ("bearish" if direction == "DOWN" else "neutral")
                except Exception:
                    continue
            return trends

        def _compute_atr(massive, tkr, trigger_tf):
            try:
                count = 30 if trigger_tf in ("5m", "15m", "30m", "1h") else 50
                candles = massive.get_candles(tkr, trigger_tf, count)
                if not candles or len(candles) < 14:
                    return 0
                ranges = [c.high - c.low for c in candles[-14:]]
                return sum(ranges) / len(ranges)
            except Exception:
                return 0

        # Dedup key for any zone we already have from the bot's real watchlist
        seen = {(z["instrument"], z["zone_timeframe"], z["zone_type"]) for z in result}

        massive_key = os.environ.get("MASSIVE_API_KEY", "")
        if massive_key:
            try:
                from lumisignals.massive_client import MassiveClient
                from lumisignals.levels_strategy import get_builtin_snr_levels
                from lumisignals.untouched_levels import calculate_adx_direction
                massive = MassiveClient(massive_key)
                for idx_ticker, display_name, mkt in [
                    ("I:SPX", "I:SPX", "stock"),
                    ("SPY", "SPY", "stock"),
                    ("C:XAUUSD", "GOLD", "forex"),
                    ("C:WTICOUSD", "OIL", "forex"),
                ]:
                    try:
                        price = massive.get_price(idx_ticker)
                        if not price:
                            continue
                        # Cache trends + ATR per model so we don't recompute per zone
                        trends_cache = {}
                        atr_cache = {}
                        # Fetch SNR for the union of all models' zone TFs in one pass
                        all_tfs = sorted({tf for tfs in MODEL_ZONE_TFS.values() for tf in tfs})
                        snr = get_builtin_snr_levels(massive, idx_ticker, all_tfs, market_type=mkt)

                        for model, zone_tfs in MODEL_ZONE_TFS.items():
                            for tf in zone_tfs:
                                data = snr.get(tf) or {}
                                for zone_type, key in [("supply", "resistance_price"), ("demand", "support_price")]:
                                    level = data.get(key)
                                    if not level:
                                        continue
                                    if (display_name, tf, zone_type) in seen:
                                        continue
                                    seen.add((display_name, tf, zone_type))

                                    if model not in trends_cache:
                                        trends_cache[model] = _compute_trends(massive, idx_ticker, model)
                                        atr_cache[model] = _compute_atr(massive, idx_ticker, MODEL_TRIGGER_TF[model])

                                    trends = trends_cache[model]
                                    atr = atr_cache[model]

                                    # Score = % of trends aligning with zone direction
                                    trade_dir = "BUY" if zone_type == "demand" else "SELL"
                                    want = "bullish" if trade_dir == "BUY" else "bearish"
                                    agree = sum(1 for d in trends.values() if d == want)
                                    total = len(trends) or 1
                                    bias_score = round((agree / total) * 100)

                                    # Tolerance for "activated" = 0.5 ATR (matches bot)
                                    if atr:
                                        activated = abs(price - level) <= 0.5 * atr
                                    else:
                                        activated = (abs(price - level) / price * 100) < 0.5

                                    result.append({
                                        "instrument": display_name,
                                        "model": model,
                                        "zone_type": zone_type,
                                        "zone_timeframe": tf,
                                        "zone_price": round(level, 2),
                                        "status": "activated" if activated else "watching",
                                        "bias_score": bias_score,
                                        "trade_direction": trade_dir,
                                        "trends": trends,
                                        "atr": round(atr, 5) if atr else 0,
                                        "distance_pct": round(abs(price - level) / price * 100, 2),
                                    })
                    except Exception:
                        pass
            except Exception:
                pass

        # Sort: activated first, then by score
        result.sort(key=lambda z: (0 if z["status"] == "activated" else 1, -z["bias_score"]))
        return jsonify({"zones": result})

    @app.route("/api/ib/status")
    def api_ib_status_public():
        """Public IB status for mobile app — no login required."""
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = rdb.get("ibkr:data:1")
        if raw:
            data = json.loads(raw)
            last_synced = data.get("last_synced", "")
            if last_synced:
                try:
                    sync_time = datetime.fromisoformat(last_synced.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - sync_time).total_seconds()
                    return jsonify({
                        "connected": age < 60,
                        "last_synced": last_synced,
                        "age_seconds": int(age),
                        "nav": data.get("account", {}).get("NetLiquidation"),
                        "positions": len(data.get("positions", [])),
                    })
                except Exception:
                    pass
        return jsonify({"connected": False, "last_synced": None, "age_seconds": None})

    # -----------------------------------------------------------------------
    # Chart Data APIs (public — market data, not user-specific)
    # -----------------------------------------------------------------------

    @app.route("/api/candles/<ticker>")
    def api_candles(ticker):
        """Fetch OHLC candles for chart display.

        Query params:
            timespan: 1m, 2m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1mo (default: 15m)
            count: number of candles (default: 200)

        Futures (MES, ES): reads from IB sync Redis cache (2m bars only).
        Forex (EUR_USD): fetches from Polygon with C: prefix.
        Stocks (SPY, AAPL): fetches from Polygon directly.
        """
        import redis as _redis
        timespan = request.args.get("timespan", "15m")
        count = int(request.args.get("count", 200))
        ticker_upper = ticker.upper()

        # Futures: read from IB Redis cache
        if ticker_upper in ("MES", "ES", "NQ", "YM", "RTY"):
            rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
            raw = rdb.get(f"ibkr:bars:{ticker_upper}:2m")
            if not raw:
                return jsonify({"candles": [], "source": "ibkr", "stale": True})
            data = json.loads(raw)
            bars = data.get("bars", [])
            candles = []
            for b in bars:
                t = b.get("time", "")
                try:
                    if isinstance(t, (int, float)):
                        ts = int(t)
                    else:
                        ts = int(datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp())
                except Exception:
                    continue
                candles.append({
                    "time": ts,
                    "open": float(b.get("open", 0)),
                    "high": float(b.get("high", 0)),
                    "low": float(b.get("low", 0)),
                    "close": float(b.get("close", 0)),
                })
            # Return last N candles
            candles = candles[-count:] if len(candles) > count else candles
            return jsonify({"candles": candles, "source": "ibkr", "ticker": ticker_upper,
                            "timespan": "2m", "front_month": data.get("front_month", "")})

        # Forex / Stocks: fetch from Polygon
        massive_key = os.environ.get("MASSIVE_API_KEY", "")
        if not massive_key:
            return jsonify({"candles": [], "error": "No Polygon API key"}), 400

        from lumisignals.massive_client import MassiveClient
        massive = MassiveClient(massive_key)

        # Map display names to Polygon tickers
        TICKER_MAP = {"GOLD": "C:XAUUSD", "OIL": "C:WTICOUSD"}
        poly_ticker = TICKER_MAP.get(ticker_upper, ticker_upper)

        # Detect ticker type and format for Polygon
        is_forex = "_" in ticker_upper
        if is_forex:
            poly_ticker = f"C:{ticker_upper.replace('_', '')}"

        try:
            candle_data = massive.get_candles(poly_ticker, timespan, count)
            candles = []
            for c in candle_data:
                try:
                    ts = int(float(c.timestamp)) if c.timestamp else 0
                except Exception:
                    ts = 0
                candles.append({
                    "time": ts,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                })
            return jsonify({"candles": candles, "source": "polygon", "ticker": ticker_upper, "timespan": timespan})
        except Exception as e:
            return jsonify({"candles": [], "error": str(e)}), 500

    @app.route("/api/levels/<ticker>")
    def api_levels(ticker):
        """Fetch S/R levels for chart overlay.

        Returns both TradingView-sourced levels (from Pine Script webhooks)
        and server-calculated levels (from Polygon data).
        """
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        ticker_upper = ticker.upper().replace("_", "")

        # Map display names to Polygon tickers for levels
        LEVELS_TICKER_MAP = {"GOLD": "C:XAUUSD", "OIL": "C:WTICOUSD"}
        poly_levels_ticker = LEVELS_TICKER_MAP.get(ticker_upper, ticker_upper)

        result = {"ticker": ticker_upper, "tv": {}, "server": {}}

        # TradingView levels from Redis
        tv_raw = rdb.get(f"tv:levels:{ticker_upper}")
        if tv_raw:
            tv_data = json.loads(tv_raw)
            result["tv"] = tv_data.get("levels", {})
            result["tv_trends"] = tv_data.get("trends", {})
            result["tv_updated"] = tv_data.get("updated_at", "")

        # Server-calculated levels from Polygon
        massive_key = os.environ.get("MASSIVE_API_KEY", "")
        if massive_key:
            try:
                from lumisignals.massive_client import MassiveClient
                from lumisignals.levels_strategy import get_builtin_snr_levels
                massive = MassiveClient(massive_key)
                is_forex = "_" in ticker or poly_levels_ticker.startswith("C:")
                market_type = "forex" if is_forex else "stock"
                snr = get_builtin_snr_levels(massive, poly_levels_ticker, ["1mo", "1w", "1d", "4h", "1h"], market_type=market_type)
                # Convert to chart format
                tf_map = {"1mo": "M", "1w": "W", "1d": "D", "4h": "4H", "1h": "1H"}
                for tf, label in tf_map.items():
                    if tf in snr:
                        result["server"][label] = {
                            "supply": snr[tf].get("resistance_price"),
                            "demand": snr[tf].get("support_price"),
                        }
            except Exception as e:
                logger.debug("Server levels error for %s: %s", ticker, e)

        return jsonify(result)

    @app.route("/chart")
    def mobile_chart_page():
        """Serve the Lightweight Charts page for mobile WebView."""
        return render_template("mobile_chart.html")

    @app.route("/ib-auth/status")
    @login_required
    def ib_auth_status():
        """Check IB Gateway connection status via sync data freshness."""
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = rdb.get("ibkr:data:1")
        auth_time = rdb.get("ib:auth_time")
        auth_time_str = auth_time.decode() if auth_time else ""

        if raw:
            data = json.loads(raw)
            last_synced = data.get("last_synced", "")
            if last_synced:
                from datetime import datetime as _dt, timezone as _tz
                try:
                    sync_time = _dt.fromisoformat(last_synced.replace("Z", "+00:00"))
                    age = (_dt.now(_tz.utc) - sync_time).total_seconds()
                    if age < 60:
                        return jsonify({
                            "authenticated": True,
                            "connected": True,
                            "auth_time": auth_time_str,
                            "serverInfo": {"serverName": "IB Gateway (Docker)", "serverVersion": f"Synced {int(age)}s ago"},
                        })
                except Exception:
                    pass
        return jsonify({"authenticated": False, "connected": False, "auth_time": auth_time_str, "error": "Sync not running or stale"})

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
            # Include if user_id matches, OR if it's a futures entry (sync doesn't set user_id)
            if order.get("user_id") == current_user.id or (
                order.get("type") == "futures" and "futures_entry" in order.get("order_id", "")
            ):
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
                    # Terminal statuses get short TTL to auto-clean
                    new_status = data.get("status", order.get("status", ""))
                    if new_status in ("expired", "superseded", "cancelled", "Cancelled", "failed", "closed"):
                        ttl = 3600  # 1 hour — enough for closed trade recording
                    else:
                        ttl = 86400
                    rdb.setex(key, ttl, json.dumps(order))
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

    @app.route("/api/ibkr/futures-bars/<ticker>", methods=["GET", "POST"])
    def api_ibkr_futures_bars(ticker):
        """Cache of 2-min IB futures bars. Sync POSTs them; strategy GETs them.

        Replaces the Polygon I:SPX feed for 2n20 — sync pulls from IB's CME-consolidated
        feed so our candles match TV's MES1! chart.

        POST body: {"bars": [{"open": ..., "high": ..., "low": ..., "close": ...,
                              "volume": ..., "time": "..."}], "front_month": "MESM26"}
        GET response: same shape + last_synced + stale flag
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        sym = ticker.upper()
        key = f"ibkr:bars:{sym}:2m"

        if request.method == "POST":
            from datetime import datetime as _dt, timezone as _tz
            body = request.get_json(silent=True) or {}
            payload = {
                "bars": body.get("bars", []),
                "front_month": body.get("front_month", ""),
                "updated_at": _dt.now(_tz.utc).isoformat(),
            }
            # 5-min TTL; sync pushes every 60s so this stays warm during normal operation.
            rdb.setex(key, 300, json.dumps(payload))
            return jsonify({"status": "ok", "count": len(payload["bars"])})

        # GET
        raw = rdb.get(key)
        if not raw:
            return jsonify({"bars": [], "stale": True, "reason": "no recent bar push"})
        return jsonify(json.loads(raw))

    @app.route("/api/ibkr/futures-position/<ticker>")
    def api_ibkr_futures_position(ticker):
        """Return the current futures position for a ticker as seen at the broker.

        Used by internally-generated strategies to verify state before placing
        entry/exit orders. Sync-key authed (internal callers only).
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = rdb.get("ibkr:data:1")
        if not raw:
            return jsonify({"connected": False, "ticker": ticker.upper(),
                            "position": 0, "reason": "no recent sync data"})
        data = json.loads(raw)
        sym = ticker.upper()
        for p in data.get("positions", []):
            if p.get("symbol") == sym and p.get("sec_type") == "FUT":
                return jsonify({
                    "connected": True,
                    "ticker": sym,
                    "position": int(p.get("quantity", 0)),
                    "avg_cost": float(p.get("avg_cost", 0)),
                    "last_synced": data.get("last_synced", ""),
                })
        return jsonify({
            "connected": True,
            "ticker": sym,
            "position": 0,
            "avg_cost": 0,
            "last_synced": data.get("last_synced", ""),
        })

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
        """Record a closed options/futures trade. Idempotent on close_exec_id when provided."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        import uuid
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        data = request.get_json()
        # Dedup: if close_exec_id was already recorded, return the existing trade_id.
        # Lets explicit-CLOSE path and auto-detector both fire safely on the same close.
        close_exec_id = str(data.get("close_exec_id", "") or "")
        if close_exec_id:
            existing = rdb.get(f"ibkr:closed_exec:{close_exec_id}")
            if existing:
                return jsonify({"status": "duplicate", "trade_id": existing.decode() if isinstance(existing, bytes) else existing})
        trade_id = str(uuid.uuid4())[:8]
        data["trade_id"] = trade_id
        # Store with 30-day TTL
        rdb.setex(f"ibkr:closed:{trade_id}", 2592000, json.dumps(data))
        if close_exec_id:
            rdb.setex(f"ibkr:closed_exec:{close_exec_id}", 2592000, trade_id)

        # Dual-write to Supabase
        try:
            from lumisignals.supabase_client import record_closed_trade, notify_trade_closed
            user_id = os.environ.get("SUPABASE_USER_ID", "")
            if user_id:
                asset_type = data.get("type", "options")
                record_closed_trade(user_id, {
                    "id": trade_id,
                    "broker": "ib",
                    "asset_type": asset_type,
                    "instrument": data.get("ticker", data.get("symbol", "")),
                    "direction": data.get("direction", ""),
                    "contracts": data.get("contracts", 1),
                    "entry_price": data.get("entry_price", 0),
                    "exit_price": data.get("exit_price", 0),
                    "realized_pl": data.get("realized_pnl", 0),
                    "stop_loss": data.get("stop_loss"),
                    "strategy": data.get("strategy", ""),
                    "model": data.get("model", ""),
                    "close_reason": data.get("close_reason", ""),
                    "won": (data.get("realized_pnl", 0) or 0) > 0,
                    "spread_type": data.get("spread_type"),
                    "sell_strike": data.get("sell_strike"),
                    "buy_strike": data.get("buy_strike"),
                    "opened_at": data.get("opened_at", ""),
                    "closed_at": data.get("closed_at", ""),
                    "duration_mins": data.get("duration_mins"),
                })
                # Push notification
                pl = data.get("realized_pnl", 0) or 0
                ticker = data.get("ticker", data.get("symbol", ""))
                direction = data.get("direction", "")
                notify_trade_closed(user_id, ticker, direction, pl, 0,
                                    data.get("close_reason", ""))
        except Exception as e:
            logger.debug("Supabase IB trade write error: %s", e)

        return jsonify({"status": "ok", "trade_id": trade_id})

    @app.route("/api/ibkr/closed-trades")
    @login_required
    def api_ibkr_closed_trades():
        """Return closed trades with optional filtering.

        Query params:
            type: "futures" or "options" (default: all)
            limit: max trades to return (default: 50)
            offset: skip first N trades (default: 0)
            days: only trades from last N days (default: all)
        """
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        trades = []
        for key in rdb.scan_iter("ibkr:closed:*"):
            raw = rdb.get(key)
            if raw:
                trades.append(json.loads(raw))
        # Sort by closed_at descending
        trades.sort(key=lambda t: t.get("closed_at", ""), reverse=True)

        # Filter by type
        trade_type = request.args.get("type")
        if trade_type:
            trades = [t for t in trades if t.get("type") == trade_type]

        # Filter by days
        days = request.args.get("days")
        if days:
            try:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat()
                trades = [t for t in trades if t.get("closed_at", "") >= cutoff]
            except Exception:
                pass

        total = len(trades)

        # Pagination
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
        if limit > 0:
            trades = trades[offset:offset + limit]

        return jsonify({"trades": trades, "total": total, "offset": offset, "limit": limit})

    @app.route("/api/ibkr/closed-trades/csv")
    @login_required
    def api_ibkr_closed_trades_csv():
        """Download all closed trades as CSV."""
        import redis as _redis
        import csv
        import io
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        trades = []
        for key in rdb.scan_iter("ibkr:closed:*"):
            raw = rdb.get(key)
            if raw:
                trades.append(json.loads(raw))
        trades.sort(key=lambda t: t.get("closed_at", ""), reverse=True)

        # Filter by type if specified
        trade_type = request.args.get("type")
        if trade_type:
            trades = [t for t in trades if t.get("type") == trade_type]

        output = io.StringIO()
        writer = csv.writer(output)

        def to_et(iso_str):
            """Convert ISO UTC timestamp to 'M/D/YYYY H:MM AM/PM' in ET."""
            if not iso_str:
                return ""
            try:
                from zoneinfo import ZoneInfo
                et = ZoneInfo("America/New_York")
            except ImportError:
                et = timezone(timedelta(hours=-4))
            try:
                dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
                return dt.astimezone(et).strftime("%-m/%-d/%Y %-I:%M %p")
            except Exception:
                return iso_str

        # Header
        writer.writerow([
            "Type", "Symbol", "Direction", "Contracts/Qty", "Entry Price", "Exit Price",
            "Realized P&L", "Strategy", "Model", "Close Reason", "Result",
            "Opened", "Closed", "Duration (min)"
        ])
        for t in trades:
            dur = ""
            try:
                if t.get("opened_at") and t.get("closed_at"):
                    o = datetime.fromisoformat(t["opened_at"].replace("Z", "+00:00"))
                    c = datetime.fromisoformat(t["closed_at"].replace("Z", "+00:00"))
                    dur = str(int((c - o).total_seconds() / 60))
            except Exception:
                pass
            pnl = t.get("realized_pnl", 0)
            writer.writerow([
                t.get("type", ""),
                t.get("symbol", t.get("ticker", "")),
                t.get("direction", ""),
                t.get("contracts", t.get("quantity", 1)),
                t.get("entry_price", ""),
                t.get("exit_price", ""),
                round(pnl, 2) if pnl else "",
                t.get("strategy", ""),
                t.get("model", ""),
                t.get("close_reason", ""),
                "WIN" if pnl and pnl > 0 else ("LOSS" if pnl and pnl < 0 else ""),
                to_et(t.get("opened_at", "")),
                to_et(t.get("closed_at", "")),
                dur,
            ])

        response = make_response(output.getvalue())
        response.headers["Content-Type"] = "text/csv"
        response.headers["Content-Disposition"] = f"attachment; filename=closed_trades_{datetime.now().strftime('%Y%m%d')}.csv"
        return response

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
            closed = get_closed_trades(client, count=500)
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

    @app.route("/api/oanda/trades/csv")
    @login_required
    def api_oanda_trades_csv():
        """Download closed FX trades as CSV."""
        import csv
        import io
        if not current_user.oanda_api_key:
            return jsonify({"error": "No Oanda credentials"}), 400
        try:
            from lumisignals.oanda_client import OandaClient
            from lumisignals.trade_tracker import get_closed_trades
            from lumisignals.signal_log import SignalLog
            import lumisignals.signal_log as _sl

            client = OandaClient(
                account_id=current_user.oanda_account_id,
                api_key=current_user.oanda_api_key,
                environment=current_user.oanda_environment or "practice",
            )
            sig_log_path = f"/opt/lumisignals/signal_log_user_{current_user.id}.json"
            old_log = _sl._log
            _sl._log = SignalLog(path=sig_log_path)

            count = int(request.args.get("count", 500))
            closed = get_closed_trades(client, count=count)
            _sl._log = old_log

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "Pair", "Direction", "Units", "Entry", "Exit", "Pips",
                "Realized P&L", "Strategy", "Model", "Close Reason", "Result",
                "Planned SL", "Planned TP", "Planned R:R", "Achieved R:R",
                "Opened", "Closed",
            ])
            for t in closed:
                pnl = t.get("realized_pl", 0)
                writer.writerow([
                    t.get("instrument", ""),
                    t.get("direction", ""),
                    t.get("units", ""),
                    t.get("entry", ""),
                    t.get("close_price", ""),
                    t.get("pips", ""),
                    round(pnl, 2),
                    t.get("strategy", t.get("strategy_id", "")),
                    t.get("model", ""),
                    t.get("close_reason", ""),
                    "WIN" if pnl > 0 else "LOSS",
                    t.get("stop_loss", ""),
                    t.get("take_profit", ""),
                    t.get("planned_rr", ""),
                    t.get("achieved_rr", ""),
                    t.get("time_opened", ""),
                    t.get("time_closed", ""),
                ])
            response = make_response(output.getvalue())
            response.headers["Content-Type"] = "text/csv"
            response.headers["Content-Disposition"] = f"attachment; filename=fx_trades_{datetime.now().strftime('%Y%m%d')}.csv"
            return response
        except Exception as e:
            logger.error("Oanda CSV error: %s", e)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/positions/close", methods=["POST"])
    def api_positions_close():
        """Manually close a single open position from the mobile app.

        Auth: X-Sync-Key header (same key the IB sync uses).
        Body:
          {
            "broker": "oanda" | "ib",
            "asset_type": "forex" | "futures" | "options",
            "instrument": "EUR_USD" | "MES" | ...,
            "broker_trade_id": "<oanda trade id or IB perm id>",
            "direction": "BUY" | "SELL" | "LONG" | "SHORT",
            "strategy": "<original strategy tag, e.g. vwap_2n20>",
            // Options-only:
            "contracts": int, "spread_type": str, "right": str,
            "expiration": "YYYYMMDD", "sell_strike": float, "buy_strike": float
          }

        Behavior per broker/asset:
          oanda/forex   — closes the specific Oanda trade ID directly via REST.
          ib/futures    — queues a CLOSE_LONG/CLOSE_SHORT order that the
                          sync's check_order_requests picks up (~10s lag).
          ib/options    — queues a manual options close on the same Redis
                          pending-order shape; sync handles it next cycle.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403

        data = request.get_json(silent=True) or {}
        broker = (data.get("broker") or "").lower()
        asset_type = (data.get("asset_type") or "").lower()
        instrument = data.get("instrument") or ""
        trade_id = data.get("broker_trade_id") or ""
        direction = (data.get("direction") or "").upper()
        strategy = data.get("strategy") or "manual_close"

        if not instrument:
            return jsonify({"error": "missing instrument"}), 400

        # ─── OANDA FOREX: close trade by ID directly ───
        if broker == "oanda" and asset_type == "forex":
            if not trade_id:
                return jsonify({"error": "missing broker_trade_id"}), 400
            try:
                import psycopg2 as _pg
                conn = _pg.connect(os.environ.get(
                    "DATABASE_URL",
                    "postgresql://lumisignals:LumiBot2026@localhost/lumisignals_db"))
                cur = conn.cursor()
                cur.execute(
                    "SELECT oanda_api_key, oanda_account_id, oanda_environment "
                    "FROM users WHERE bot_active = true AND oanda_api_key IS NOT NULL "
                    "ORDER BY id LIMIT 1")
                row = cur.fetchone()
                conn.close()
                if not row:
                    return jsonify({"error": "no oanda creds configured"}), 500
                api_key, acct_id, env = row
                from lumisignals.oanda_client import OandaClient
                oc = OandaClient(account_id=acct_id, api_key=api_key,
                                 environment=env or "practice")
                resp = oc.close_trade(trade_id)
                return jsonify({"status": "closed", "broker": "oanda",
                                "trade_id": trade_id, "response": resp})
            except Exception as e:
                logger.error("Oanda close failed for %s: %s", trade_id, e)
                return jsonify({"error": f"Oanda close failed: {e}"}), 500

        # ─── IB FUTURES: enqueue CLOSE_LONG/CLOSE_SHORT ───
        if broker == "ib" and asset_type == "futures":
            close_dir = "CLOSE_LONG" if direction in ("BUY", "LONG") else "CLOSE_SHORT"
            import redis as _redis
            import uuid as _uuid
            rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

            # Safety net: validate against the live IB position so rapid
            # taps can't compound into flipping the position. We read the
            # latest IB snapshot from ibkr:data:1 (refreshed every ~10s).
            requested_qty = int(data.get("contracts", 1))
            ib_qty = None
            try:
                snap = rdb.get("ibkr:data:1")
                if snap:
                    snap_data = json.loads(snap)
                    for p in snap_data.get("positions", []):
                        if p.get("symbol") == instrument and p.get("sec_type") == "FUT":
                            ib_qty = int(p.get("quantity") or 0)
                            break
            except Exception:
                pass
            if ib_qty is not None:
                # Direction must match IB's net side; never let a "close"
                # accidentally flip the position the other way.
                if close_dir == "CLOSE_LONG" and ib_qty <= 0:
                    return jsonify({"status": "rejected",
                                    "reason": f"IB is not long {instrument} (qty={ib_qty})"}), 200
                if close_dir == "CLOSE_SHORT" and ib_qty >= 0:
                    return jsonify({"status": "rejected",
                                    "reason": f"IB is not short {instrument} (qty={ib_qty})"}), 200
                # Cap to what's actually open so the close can't over-trade
                capped = min(requested_qty, abs(ib_qty))
                if capped <= 0:
                    return jsonify({"status": "rejected",
                                    "reason": "Already flat"}), 200
                if capped < requested_qty:
                    logger.info("Manual close capped: requested %d, IB has %d → %d",
                                requested_qty, abs(ib_qty), capped)
                requested_qty = capped

            # 30s dedup per (instrument, direction) so multiple taps coalesce.
            # Pine close signals come through the webhook path; manual closes
            # come through here. Independent dedup keys avoid cross-blocking.
            dedup_key = f"manual_close:{instrument}:{close_dir}"
            existing = rdb.get(dedup_key)
            if existing:
                return jsonify({"status": "skipped",
                                "reason": "An identical close was just queued",
                                "order_id": existing.decode() if isinstance(existing, bytes) else existing}), 200

            order_id = str(_uuid.uuid4())[:8]
            order = {
                "order_id": order_id,
                "queued_at": datetime.now(timezone.utc).isoformat(),
                "user_id": 1,
                "ticker": instrument,
                "type": "futures",
                "direction": close_dir,
                "strategy": strategy,
                "reason": "Manual close (mobile)",
                "contracts": requested_qty,
                "status": "queued",
            }
            rdb.setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))
            rdb.setex(dedup_key, 30, order_id)
            return jsonify({"status": "queued", "broker": "ib",
                            "action": close_dir, "ticker": instrument,
                            "contracts": requested_qty,
                            "order_id": order_id})

        # ─── IB OPTIONS: enqueue manual spread close ───
        if broker == "ib" and asset_type == "options":
            import redis as _redis
            import uuid as _uuid
            rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
            order_id = str(_uuid.uuid4())[:8]
            order = {
                "order_id": order_id,
                "queued_at": datetime.now(timezone.utc).isoformat(),
                "user_id": 1,
                "ticker": instrument,
                "type": "options_close",
                "strategy": strategy,
                "reason": "Manual close (mobile)",
                "contracts": int(data.get("contracts", 1)),
                "spread_type": data.get("spread_type", ""),
                "right": data.get("right", ""),
                "expiration": data.get("expiration", ""),
                "sell_strike": float(data.get("sell_strike") or 0),
                "buy_strike": float(data.get("buy_strike") or 0),
                "status": "queued",
            }
            rdb.setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))
            return jsonify({"status": "queued", "broker": "ib",
                            "action": "options_close", "ticker": instrument,
                            "order_id": order_id})

        return jsonify({"error": f"unsupported broker/asset: {broker}/{asset_type}"}), 400

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
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Internal endpoint — invalid or missing X-Sync-Key header"}), 403
        data = request.get_json(silent=True) or {}
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

        # Built-in Polygon levels (replaces LumiTrade API)
        massive_key = os.environ.get("MASSIVE_API_KEY", "")
        massive = None
        if massive_key:
            from lumisignals.massive_client import MassiveClient
            from lumisignals.untouched_levels import find_untouched_levels, calculate_adx_direction
            massive = MassiveClient(massive_key)

        results = []
        for ticker in tickers:
            item = {"ticker": ticker, "server": {}, "tradingview": {}, "tv_trends": {}, "server_trends": {}, "tv_updated": ""}

            # Determine if ticker is forex (e.g. EURUSD, GBPUSD)
            is_forex = len(ticker) == 6 and ticker[:3].isalpha() and ticker[3:].isalpha() and ticker not in ("GOOGL",)

            if massive:
                if is_forex:
                    poly_ticker = f"C:{ticker}"
                else:
                    poly_ticker = ticker

                for tf, tf_label in interval_to_tf.items():
                    try:
                        count = 30 if tf in ("3mo", "1mo", "1w") else 50
                        candles = massive.get_candles(poly_ticker, tf, count)
                        if not candles or len(candles) < 3:
                            continue
                        price = candles[-1].close
                        highs = [c.high for c in reversed(candles)]
                        lows = [c.low for c in reversed(candles)]
                        s1, s2, d1, d2 = find_untouched_levels(highs, lows, price, lookback=10)
                        item["server"][tf_label] = {
                            "supply": s1, "supply2": s2,
                            "demand": d1, "demand2": d2,
                        }
                        # ADX trend
                        adx_dir = calculate_adx_direction(candles)
                        if adx_dir:
                            item["server_trends"][tf_label] = adx_dir.get("direction", "SIDE")
                    except Exception as e:
                        logger.debug("Compare level error %s %s: %s", ticker, tf, e)
            else:
                item["server"]["error"] = "No Polygon API key configured"

            # --- TradingView levels from Redis ---
            tv_raw = rdb.get(f"tv:levels:{ticker}")
            if tv_raw:
                tv_data = json.loads(tv_raw)
                item["tradingview"] = tv_data.get("levels", {})
                item["tv_trends"] = tv_data.get("trends", {})
                item["tv_updated"] = tv_data.get("updated_at", "")

            # --- LumiTrade API levels (third source) ---
            item["lumitrade"] = {}
            item["lt_trends"] = {}
            if snr_api_key:
                import requests as _requests
                session = _requests.Session()
                session.headers["Authorization"] = f"Bearer {snr_api_key}"
                try:
                    resp = session.get(
                        f"{snr_base_url}/partners/technical-analysis/snr/frequency/",
                        params={"ticker": ticker, "intervals": ",".join(snr_intervals),
                                "type": "forex" if is_forex else "stock", "days": 256},
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

                try:
                    resp2 = session.get(
                        f"{snr_base_url}/partners/technical-analysis/trade-builder-setup",
                        params={"ticker": ticker, "period": 14,
                                "market": "forex" if is_forex else "stock",
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
                levels = scan_ticker(client, ticker, price, ["1mo", "1w", "1d"])
                for tf_label, lvl in levels.items():
                    # Swing setups only trigger on M/W levels (D fetched for trend display only)
                    if tf_label not in ("M", "W"):
                        continue
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
                        # Collect M/W/D trends for display
                        mtf_trends = {}
                        for ttf in ["M", "W", "D"]:
                            tlvl = levels.get(ttf)
                            mtf_trends[ttf] = tlvl.trend if tlvl else "—"
                        all_setups.append({
                            "ticker": ticker, "name": TICKER_NAMES.get(ticker, ""), "price": round(price, 2), "level": round(level_price, 2),
                            "level_type": level_type, "tf": tf_label,
                            "tf_name": {"M": "Monthly", "W": "Weekly"}.get(tf_label, tf_label),
                            "distance_pct": round(dist_pct, 2), "direction": direction,
                            "trend": lvl.trend, "adx": lvl.adx, "score": score,
                            "mtf_trends": mtf_trends, "trend_labels": ["M", "W", "D"],
                        })
            except Exception:
                continue

        # Scan core tickers — intraday (D levels) + scalp (4H levels)
        for ticker in core_list:
            try:
                candles_1d = client.get_candles(ticker, "1d", 2)
                if not candles_1d:
                    continue
                price = candles_1d[-1].close
                # Fetch W/D/4H/1H for both intraday and scalp
                levels = scan_ticker(client, ticker, price, ["1w", "1d", "4h", "1h"])

                for tf_label, lvl in levels.items():
                    # Intraday: only D levels
                    # Scalp: only 4H levels
                    if tf_label == "D":
                        trade_type = "intraday"
                        tf_display = "Daily"
                        # W / D / 1H trends
                        mtf_trends = {}
                        for ttf, lbl in [("W", "W"), ("D", "D"), ("1H", "1H")]:
                            tlvl = levels.get(ttf)
                            mtf_trends[lbl] = tlvl.trend if tlvl else "—"
                        trend_labels = ["W", "D", "1H"]
                    elif tf_label == "4H":
                        trade_type = "scalp"
                        tf_display = "4-Hour"
                        # 4H / 1H trends (5m not fetched server-side)
                        mtf_trends = {}
                        for ttf, lbl in [("4H", "4H"), ("1H", "1H")]:
                            tlvl = levels.get(ttf)
                            mtf_trends[lbl] = tlvl.trend if tlvl else "—"
                        trend_labels = ["4H", "1H"]
                    else:
                        continue

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
                            "tf_name": tf_display,
                            "distance_pct": round(dist_pct, 2), "direction": direction,
                            "trend": lvl.trend, "adx": lvl.adx, "score": score,
                            "mtf_trends": mtf_trends, "trend_labels": trend_labels,
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
        """Trade-signal queue accepting either TV alerts (body `key`) or internal callers.

        Auth: passes if EITHER
          - `X-Sync-Key` header matches IBKR_SYNC_KEY (internal callers like swing_scanner), OR
          - body `key` field matches TV_WEBHOOK_KEY (TradingView alerts).

        TV is the real-time data source for futures (MES/ES) since the IB account
        lacks a CME real-time market data subscription. The TV Pine Script alert
        fires on bar close with the canonical 2n20 logic — same script the bot's
        internal strategy mirrors — so this gives us scalp-grade lag (~10-20s)
        without needing to pay for IB market data.
        """
        import redis as _redis
        import uuid

        data = request.get_json(silent=True) or {}
        sync_key = request.headers.get("X-Sync-Key", "")
        body_key = data.get("key", "")
        ok_sync = sync_key == os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026")
        ok_tv = body_key and body_key == os.environ.get("TV_WEBHOOK_KEY", "lumisignals2026")
        if not (ok_sync or ok_tv):
            return jsonify({"error": "Invalid auth — provide X-Sync-Key header or body key"}), 403

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

        # ─── ORB BUTTERFLY PATH (SPX 0DTE leg-in) ───
        # Pine alert carries the full butterfly plan (K1/K2/K3, debit/credit
        # targets, OR context, VIX, reversal flag). Hand off to the dedicated
        # state machine in orb_butterfly_handler.
        if strategy == "orb_butterfly":
            rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
            # Verify required fields up front so we don't queue garbage
            required = ("long_strike", "body_strike", "wing_strike", "direction")
            missing = [f for f in required if f not in data]
            if missing:
                return jsonify({"error": "missing orb_butterfly fields: " + ",".join(missing)}), 400
            try:
                from lumisignals.orb_butterfly_handler import queue_butterfly
                bid = queue_butterfly(rdb, data)
                return jsonify({"status": "queued",
                                "strategy": "orb_butterfly",
                                "butterfly_id": bid,
                                "direction": data.get("direction"),
                                "spread_type": data.get("spread_type"),
                                "K1_K2_K3": [data.get("long_strike"), data.get("body_strike"), data.get("wing_strike")]})
            except Exception as e:
                logger.error("orb_butterfly queue failed: %s", e)
                return jsonify({"error": f"butterfly queue failed: {e}"}), 500

        # ─── FUTURES PATH ───
        if trade_type == "futures":
            rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Refuse to queue if IB sync is offline. Better to skip the trade
            # than to pile up stale orders that fire on reconnect. User's pref:
            # "rather not trade than have stale orders build up".
            sync_alive = False
            try:
                ib_raw = rdb.get("ibkr:data:1")
                if ib_raw:
                    ib_data = json.loads(ib_raw)
                    last_sync_str = ib_data.get("last_synced", "")
                    if last_sync_str:
                        last_dt = datetime.fromisoformat(last_sync_str.replace("Z", "+00:00"))
                        age = (datetime.now(timezone.utc) - last_dt).total_seconds()
                        sync_alive = age < 90  # stale if no push in last 90s
            except Exception:
                sync_alive = False
            if not sync_alive:
                return jsonify({
                    "status": "skipped",
                    "reason": "IB sync offline — order not queued (re-auth IB Gateway via VNC)",
                    "ticker": ticker, "direction": direction,
                })

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
            # Pine's full trade plan (ORB sends all of these; 2n20 sends none).
            # Sync uses stop_price/target_price to place bracket children
            # instead of computing its own stop from config. The rest gets
            # stored on the position metadata for the dashboard/journal.
            for fld in (
                "entry_price", "stop_price", "target_price",
                "vix", "or_high", "or_low", "or_range",
                "stop_size", "stop_reason", "reversal",
            ):
                if fld in data:
                    order[fld] = data[fld]
            rdb.setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))
            # 30s dedup — only protects against accidental webhook retries from TV
            # itself. Pine's `alert.freq_once_per_bar_close` already ensures one
            # alert per bar (every 2 min), so anything past 30s is a legitimate
            # new bar's entry that we want to take.
            rdb.setex(dedup_key, 30, "1")

            # Email alert — fired in a background thread so we respond to TV
            # within ms. SMTP can take 10s+ to time out (DO blocks port 587),
            # which made TV fail webhook delivery even when the order was queued.
            import threading
            def _bg_alert():
                try:
                    from lumisignals.alerts import send_alert, AlertType
                    alert_pass = os.environ.get("ALERT_EMAIL_PASSWORD", "")
                    if alert_pass:
                        send_alert(AlertType.TRADE_OPENED,
                                   f"Futures: {direction} {ticker} — {strategy}",
                                   "TradingView 2n20 signal",
                                   details={"Ticker": ticker, "Direction": direction,
                                            "Strategy": strategy,
                                            "Contracts": str(override_contracts or 1)},
                                   smtp_pass=alert_pass)
                except Exception:
                    pass
            threading.Thread(target=_bg_alert, daemon=True).start()

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
