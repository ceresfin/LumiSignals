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


def _get_oanda_md_client():
    """OANDA client for compare-page forex market data, built from env
    (OANDA_API_KEY / OANDA_ACCOUNT_ID / OANDA_ENVIRONMENT). Returns None
    if creds are absent. Forex levels come from OANDA — the same feed the
    bot trades on and the TradingView OANDA charts use — so they match;
    Polygon/Massive does not carry an OANDA-comparable forex feed."""
    ak = os.environ.get("OANDA_API_KEY", "")
    acc = os.environ.get("OANDA_ACCOUNT_ID", "")
    if not ak or not acc:
        return None
    try:
        from lumisignals.oanda_client import OandaClient
        return OandaClient(account_id=acc, api_key=ak,
                           environment=os.environ.get("OANDA_ENVIRONMENT", "practice"))
    except Exception as e:
        logger.warning("OANDA md client init failed: %s", e)
        return None


# TF interval key → (display label, OANDA granularity). OANDA tops out at
# monthly (no quarterly), and its daily candles roll at the 5pm-ET NY
# close — exactly the FX day TradingView's OANDA charts use.
_OANDA_TF_SPECS = [
    ("1mo", "M", "M"), ("1w", "W", "W"), ("1d", "D", "D"),
    ("4h", "4H", "H4"), ("1h", "1H", "H1"),
    ("30m", "30M", "M30"), ("15m", "15M", "M15"),
]


def _oanda_forex_levels(oc, ticker):
    """SRV supply/demand + trend for a forex ticker, computed from OANDA
    bars via the same find_htf_levels used for Polygon stocks/indices.
    Returns (server_dict, trends_dict, current_price)."""
    from lumisignals.untouched_levels import (
        find_htf_levels, HTF_TF_LOOKBACK, calculate_adx_direction)
    from lumisignals.candle_classifier import CandleData
    instrument = f"{ticker[:3]}_{ticker[3:]}"  # EURUSD -> EUR_USD
    server, trends = {}, {}
    current_price = None
    for tf_key, tf_label, gran in _OANDA_TF_SPECS:
        try:
            lb = HTF_TF_LOOKBACK.get(tf_key, 50)
            raw = oc.get_candles(instrument, gran, lb + 5)  # oldest-first
            cds = [CandleData(
                       open=float(c["mid"]["o"]), high=float(c["mid"]["h"]),
                       low=float(c["mid"]["l"]), close=float(c["mid"]["c"]),
                       timestamp=c["time"])
                   for c in raw if c.get("mid")]
            if len(cds) < 3:
                continue
            price = cds[-1].close
            if current_price is None or tf_key in ("15m", "30m", "1h"):
                current_price = price
            highs = [c.high for c in reversed(cds)]
            lows = [c.low for c in reversed(cds)]
            s1, s2, d1, d2 = find_htf_levels(highs, lows, price, lookback=lb)
            recent_highs = [c.high for c in cds[-12:]]
            recent_lows = [c.low for c in cds[-12:]]
            server[tf_label] = {
                "supply": s1, "supply2": s2, "demand": d1, "demand2": d2,
                "range_high": max(recent_highs) if recent_highs else None,
                "range_low": min(recent_lows) if recent_lows else None,
            }
            direction, _adx = calculate_adx_direction(cds, period=14)
            trends[tf_label] = direction
        except Exception as e:
            logger.debug("OANDA forex level err %s %s: %s", ticker, tf_key, e)
    return server, trends, current_price


def _polygon_levels(massive, poly_ticker):
    """SRV supply/demand + trend from Polygon/Massive bars via the same
    find_htf_levels. Works for stocks/indices (bare/I: ticker) and forex
    (C: ticker, now 5pm-ET aggregated). Returns (server, trends, price)."""
    from lumisignals.untouched_levels import (
        find_htf_levels, HTF_TF_LOOKBACK, calculate_adx_direction)
    interval_to_tf = {"3mo": "Q", "1mo": "M", "1w": "W", "1d": "D",
                      "4h": "4H", "1h": "1H", "30m": "30M", "15m": "15M"}
    server, trends = {}, {}
    current_price = None
    for tf, tf_label in interval_to_tf.items():
        try:
            lb = HTF_TF_LOOKBACK.get(tf, 50)
            candles = massive.get_candles(poly_ticker, tf, lb + 5)
            if not candles or len(candles) < 3:
                continue
            price = candles[-1].close
            if current_price is None or tf in ("15m", "30m", "1h"):
                current_price = price
            highs = [c.high for c in reversed(candles)]
            lows = [c.low for c in reversed(candles)]
            s1, s2, d1, d2 = find_htf_levels(highs, lows, price, lookback=lb)
            recent_highs = [c.high for c in candles[-12:]]
            recent_lows = [c.low for c in candles[-12:]]
            server[tf_label] = {
                "supply": s1, "supply2": s2, "demand": d1, "demand2": d2,
                "range_high": max(recent_highs) if recent_highs else None,
                "range_low": min(recent_lows) if recent_lows else None,
            }
            direction, _adx = calculate_adx_direction(candles, period=14)
            trends[tf_label] = direction
        except Exception as e:
            logger.debug("Polygon level err %s %s: %s", poly_ticker, tf, e)
    return server, trends, current_price


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
    # Preserve dict insertion order in JSON responses. By default Flask
    # sorts keys alphabetically, which reorders trend timeframe keys
    # from natural order (5M, 15M, 1H) to alphabetical (15M, 1H, 5M).
    app.config["JSON_SORT_KEYS"] = False
    # Flask 2.2+ moved to provider-based JSON; configure that too so
    # the setting takes effect across versions.
    try:
        app.json.sort_keys = False
    except AttributeError:
        pass

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

        # Futures settings — per-strategy contract caps. Each strategy
        # has its own knob so loosening (say) ORB sizing doesn't
        # accidentally affect 2n20, and vice versa. Hard cap is applied
        # in the webhook handler before placing the order.
        futures_stop_loss = db.Column(db.Float, default=25.0)  # Stop loss in dollars per contract
        futures_contracts = db.Column(db.Integer, default=1)   # 2n20 MES contracts per entry
        orb_futures_contracts = db.Column(db.Integer, default=1)  # ORB MES contracts per entry

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
            current_user.orb_futures_contracts = max(1, int(request.form.get("orb_futures_contracts", 1) or 1))

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

        # Response is the same for every viewer (uses the master watchlist
        # at watchlist:1:{model}), so serve a 60s Redis-cached copy when
        # available. Building the response touches ~200 Polygon calls
        # across 19 supplemental tickers — ~25s cold, ~50ms warm.
        CACHE_KEY = "api:watchlist:zones:v2"
        CACHE_TTL = 300   # 5 min — cold rebuild costs many Polygon calls
                           # so we trade staleness for endpoint reliability.
                           # The bot still writes fresh per-model watchlists
                           # every cycle; this cache is only the API view.
        try:
            cached = rdb.get(CACHE_KEY)
            if cached:
                resp = make_response(cached)
                resp.headers["Content-Type"] = "application/json"
                resp.headers["X-Cache"] = "HIT"
                return resp
        except Exception:
            pass

        # Projected target reuses the bot's own target finder so the chart
        # shows exactly the TP the strategy would aim for at trigger time.
        from lumisignals.levels_strategy import compute_target_level

        def _poly_ticker_for(instrument: str) -> tuple:
            """Return (poly_ticker, market_type) for SNR lookup."""
            inst = instrument.upper()
            if "_" in inst:
                return f"C:{inst.replace('_','')}", "forex"
            if inst.startswith("I:") or inst.startswith("X:"):
                return inst, "stock"
            if inst.startswith("C:"):
                return inst, "forex"
            if len(inst) == 6 and inst.isalpha():
                return f"C:{inst}", "forex"
            return inst, "stock"

        def _project_target(massive, instrument, model, direction, entry, stop_distance, atr):
            poly_ticker, market_type = _poly_ticker_for(instrument)
            return compute_target_level(
                massive, model, poly_ticker, market_type,
                direction, entry, stop_distance, atr,
            )

        # Pre-init Massive client once for the whole request
        _massive = None
        try:
            massive_key = os.environ.get("MASSIVE_API_KEY", "")
            if massive_key:
                from lumisignals.massive_client import get_shared_client
                _massive = get_shared_client(massive_key)
        except Exception:
            _massive = None

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

                # Projected trade plan: what entry/stop the bot WOULD use
                # if this zone fires. Matches levels_strategy.py logic —
                # entry = zone_price, stop = entry ± 3 × trigger-TF ATR.
                # Target is left empty here; the chart computes it from
                # the S/R levels endpoint it already fetches.
                # Direction fallback: some bot paths leave trade_direction
                # blank; derive it from zone_type (supply → SELL, demand → BUY)
                # so projection still works for all three durations.
                effective_dir = trade_dir
                if not effective_dir:
                    if zone_type == "supply":
                        effective_dir = "SELL"
                    elif zone_type == "demand":
                        effective_dir = "BUY"
                projected_entry = round(zone_price, 5) if zone_price else None
                projected_stop = None
                projected_target = None
                if atr and zone_price:
                    stop_distance = 3 * atr
                    if effective_dir == "BUY":
                        projected_stop = round(zone_price - stop_distance, 5)
                    elif effective_dir == "SELL":
                        projected_stop = round(zone_price + stop_distance, 5)
                    # Skip the Polygon-backed target projection for FX
                    # zones — they don't have meaningful Polygon S/R coverage
                    # and the call adds ~1s per zone. FX zones fall through
                    # to the 2R fallback below.
                    is_fx_zone = "_" in (instrument or "")
                    if _massive and effective_dir and not is_fx_zone:
                        tgt = _project_target(_massive, instrument, model,
                                              effective_dir, zone_price,
                                              stop_distance, atr)
                        if tgt is not None:
                            projected_target = round(tgt, 5)
                    # Fallback: if no qualifying S/R level exists (or Massive
                    # isn't reachable, or we skipped for FX), draw a 2R
                    # target so the chart always has SOMETHING to show.
                    if projected_target is None and effective_dir:
                        rr_distance = 2 * stop_distance
                        if effective_dir == "BUY":
                            projected_target = round(zone_price + rr_distance, 5)
                        elif effective_dir == "SELL":
                            projected_target = round(zone_price - rr_distance, 5)

                result.append({
                    "instrument": instrument,
                    "model": model,
                    "zone_type": zone_type,
                    "zone_timeframe": zone_tf,
                    "zone_price": round(zone_price, 5),
                    "status": status,
                    "bias_score": bias_score,
                    "trade_direction": effective_dir,
                    "trends": trends,
                    "atr": round(atr, 5) if atr else 0,
                    "projected_entry": projected_entry,
                    "projected_stop": projected_stop,
                    "projected_target": projected_target,
                    # Unix seconds; 0 when never activated. Mobile renders
                    # "Activated Xh ago"; chart drops a triangle at this ts.
                    "activated_at": z.get("activated_at") or 0,
                })

        # Supplemental always-on zones for key indices/commodities. Mirrors the
        # bot's real scan structure (model-aware zone_tfs, trend_tfs, ATR) so
        # the mobile cards look identical to forex zones — and stays visible
        # outside market hours when the bot's stock scan is gated off.
        # Tidewater zone TFs (matches lumisignals.levels_strategy.ModelConfig).
        # SCALP dropped 15m on 2026-05-15 — 15m and 1h zones came from the
        # same wick. INTRADAY dropped 1w on 2026-05-16 alongside the
        # trigger-TF switch (1h → 15m) and the 1H N=15 direction gate.
        MODEL_ZONE_TFS = {
            "scalp":    ["1h"],
            "intraday": ["1d"],
            "swing":    ["1w", "1mo"],
        }
        MODEL_TREND_TFS = {
            "scalp":    [("5m", "5M"), ("15m", "15M"), ("1h", "1H")],
            "intraday": [("15m", "15M"), ("1h", "1H"), ("1d", "Daily")],
            "swing":    [("1d", "Daily"), ("1w", "Weekly"), ("1mo", "Monthly")],
        }
        MODEL_TRIGGER_TF = {"scalp": "5m", "intraday": "15m", "swing": "1d"}

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
                from lumisignals.massive_client import get_shared_client
                from lumisignals.levels_strategy import get_builtin_snr_levels
                from lumisignals.untouched_levels import calculate_adx_direction
                massive = get_shared_client(massive_key)
                # Always-on watchlist for the mobile UI. Lives alongside the
                # bot's market-hours-gated scan so high-interest names are
                # visible 24/7 (pre/post-market the bot writes 0 stock zones).
                # Curated for: index/commodity benchmarks, the Mag-7 you
                # actually trade, and high-options-volume single names where
                # SNR-zone setups tend to fire (MU/AMD/SMCI/COIN/MSTR/PLTR).
                # Adding tickers here scales endpoint cost roughly linearly —
                # keep the list focused.
                SUPPLEMENTAL_TICKERS = [
                    # Benchmarks
                    ("I:SPX", "I:SPX", "stock"),
                    ("SPY", "SPY", "stock"),
                    ("QQQ", "QQQ", "stock"),
                    ("IWM", "IWM", "stock"),
                    ("C:XAUUSD", "GOLD", "forex"),
                    ("C:WTICOUSD", "OIL", "forex"),
                    # Mag-7
                    ("AAPL", "AAPL", "stock"),
                    ("MSFT", "MSFT", "stock"),
                    ("NVDA", "NVDA", "stock"),
                    ("GOOGL", "GOOGL", "stock"),
                    ("AMZN", "AMZN", "stock"),
                    ("META", "META", "stock"),
                    ("TSLA", "TSLA", "stock"),
                    # High-options-volume single names
                    ("AMD", "AMD", "stock"),
                    ("MU", "MU", "stock"),
                    ("SMCI", "SMCI", "stock"),
                    ("AVGO", "AVGO", "stock"),
                    ("COIN", "COIN", "stock"),
                    ("MSTR", "MSTR", "stock"),
                    ("PLTR", "PLTR", "stock"),
                    ("NFLX", "NFLX", "stock"),
                ]
                # Hard time budget for the supplemental loop. Each ticker
                # costs ~5-10 Polygon calls; before this budget we observed
                # the endpoint hanging >150s on a cold cache and returning
                # nothing to mobile. Whatever ticker we're mid-flight on
                # gets dropped if the budget elapses; the bot watchlist
                # part above is guaranteed to make it through first.
                import time as _supp_time
                _supp_deadline = _supp_time.time() + 15.0
                for idx_ticker, display_name, mkt in SUPPLEMENTAL_TICKERS:
                    if _supp_time.time() > _supp_deadline:
                        logger.info("watchlist/zones: supplemental budget "
                                    "exhausted before %s", display_name)
                        break
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

                                    # Projected entry/stop/target (matches forex branch)
                                    proj_entry = round(level, 2)
                                    proj_stop = None
                                    proj_target = None
                                    if atr:
                                        stop_dist = 3 * atr
                                        if trade_dir == "BUY":
                                            proj_stop = round(level - stop_dist, 2)
                                        else:
                                            proj_stop = round(level + stop_dist, 2)
                                        if _massive:
                                            tgt = _project_target(_massive, idx_ticker, model,
                                                                  trade_dir, level, stop_dist, atr)
                                            if tgt is not None:
                                                proj_target = round(tgt, 2)
                                        # 2R fallback so the chart always
                                        # has a target line.
                                        if proj_target is None and trade_dir:
                                            rr = 2 * stop_dist
                                            if trade_dir == "BUY":
                                                proj_target = round(level + rr, 2)
                                            else:
                                                proj_target = round(level - rr, 2)
                                    result.append({
                                        "instrument": display_name,
                                        "model": model,
                                        "zone_type": zone_type,
                                        "zone_timeframe": tf,
                                        "zone_price": round(level, 2),
                                        "status": "activated" if activated else "watching",
                                        "bias_score": bias_score,
                                        "trade_direction": trade_dir,
                                        "projected_entry": proj_entry,
                                        "projected_stop": proj_stop,
                                        "projected_target": proj_target,
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
        payload = json.dumps({"zones": result})
        try:
            rdb.setex(CACHE_KEY, CACHE_TTL, payload)
        except Exception:
            pass
        resp = make_response(payload)
        resp.headers["Content-Type"] = "application/json"
        resp.headers["X-Cache"] = "MISS"
        return resp

    @app.route("/api/ib/reauth", methods=["POST"])
    def api_ib_reauth():
        """Mobile-friendly Reauth trigger. Auth via X-Sync-Key header
        (matches /api/positions/close pattern). POSTs to the local CPAPI
        gateway's /iserver/reauthenticate so the user doesn't have to
        navigate to bot.lumitrade.ai → settings → button — they can
        trigger the reauth right from the mobile app.

        Note: this only refreshes a session IBeam still has cookies for.
        If IBeam is fully logged out, a full browser login at /ib-auth
        is still required.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401
        import requests as _req
        cpapi_url = os.environ.get("CPAPI_BASE_URL", "https://localhost:5000/v1/api")
        try:
            resp = _req.post(f"{cpapi_url}/iserver/reauthenticate",
                             verify=False, timeout=15)
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text[:500]}
            return jsonify({
                "ok": resp.ok,
                "status_code": resp.status_code,
                "body": body,
            }), 200 if resp.ok else 502
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 502

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

        from lumisignals.massive_client import get_shared_client
        massive = get_shared_client(massive_key)

        # Map display names to Polygon tickers
        TICKER_MAP = {"GOLD": "C:XAUUSD", "OIL": "C:WTICOUSD"}
        # Cash indexes need Polygon's "I:" prefix. Plain SPX/NDX/RUT
        # return 0 bars without it (used by the dashboard Swing Trade
        # Panel for index option setups).
        INDEX_SYMBOLS = {"SPX", "NDX", "RUT", "VIX", "DJI"}
        poly_ticker = TICKER_MAP.get(ticker_upper, ticker_upper)

        # Detect ticker type and format for Polygon.
        # Accept BOTH "USD_CAD" and "USDCAD" — some callers (positions/trades
        # nav) strip the underscore. A 6-letter all-alpha symbol that isn't
        # in a stock-style mapping is treated as forex.
        is_forex = (
            "_" in ticker_upper
            or poly_ticker.startswith("C:")
            or (len(ticker_upper) == 6 and ticker_upper.isalpha()
                and ticker_upper not in TICKER_MAP)
        )
        if is_forex:
            poly_ticker = f"C:{ticker_upper.replace('_', '')}"
        elif ticker_upper in INDEX_SYMBOLS:
            poly_ticker = f"I:{ticker_upper}"

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
                from lumisignals.massive_client import get_shared_client
                from lumisignals.levels_strategy import get_builtin_snr_levels
                massive = get_shared_client(massive_key)
                # Detect forex: explicit underscore, C:-prefix, or a
                # 6-letter all-alpha symbol like AUDUSD/EURUSD/GBPJPY.
                # The chart strips the underscore before calling this
                # endpoint, so we can't rely on "_" alone.
                is_forex = (
                    "_" in ticker
                    or poly_levels_ticker.startswith("C:")
                    or (len(ticker_upper) == 6 and ticker_upper.isalpha())
                )
                # When forex with no C: prefix yet, add it so Polygon
                # routes to its forex aggregates endpoint
                if is_forex and not poly_levels_ticker.startswith("C:"):
                    poly_levels_ticker = "C:" + ticker_upper
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

    # ─── DASHBOARD SWING-TRADE PANEL ENDPOINTS ─────────────────────────
    # Three endpoints powering the bottom-of-Dashboard trade-setup panel:
    #   GET  /api/swing-setup           → compute setup (analysis)
    #   POST /api/option-spread/order   → place IB combo (action)
    #   POST /api/option-spread/close   → close IB combo (action)
    # All login_required (Flask session). Both order endpoints gated on
    # Redis key `equity:orders_enabled=1` (off by default until verified).

    @app.route("/api/mtf-scan")
    def api_mtf_scan():
        """Serve the latest fast MTF scan (produced by the scanner daemon).

        Public read (market data only, no user state). Reads the cached
        shortlist the background daemon writes to Redis `mtf:scan:latest` and
        applies optional filters — the scan itself is NOT computed here, so the
        response is an instant cache read regardless of universe size.

        Query params (all optional):
          asset_class — stock | index | fx | crypto (repeatable, comma-sep)
          side        — LONG | SHORT
          min_score   — 0..3
          sort        — dist | score | vol_rank   (default dist, asc)
          limit       — cap rows returned
        Empty cache (daemon not warmed yet) → {results: [], warming: true}.
        """
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = rdb.get("mtf:scan:latest")
        if not raw:
            return jsonify({"results": [], "warming": True,
                            "scanned_at": None, "stale": True})

        payload = json.loads(raw)
        rows = payload.get("results", [])

        # Staleness: scan older than ~10 min (daemon cadence is 5 min RTH).
        stale = True
        scanned_at = payload.get("scanned_at")
        if scanned_at:
            try:
                from datetime import datetime, timezone
                ts = datetime.fromisoformat(scanned_at)
                age = (datetime.now(timezone.utc) - ts).total_seconds()
                stale = age > 600
            except Exception:
                pass

        # Filters
        assets = request.args.get("asset_class", "")
        if assets:
            wanted = {a.strip().lower() for a in assets.split(",") if a.strip()}
            rows = [r for r in rows if r.get("asset_class") in wanted]
        # `group` is the finer cut: high_vol/megacap/largecap/etf for stocks,
        # else == asset_class (index/fx/crypto).
        group = request.args.get("group", "")
        if group:
            wanted_g = {g.strip().lower() for g in group.split(",") if g.strip()}
            rows = [r for r in rows if r.get("group") in wanted_g]
        side = (request.args.get("side") or "").upper()
        if side in ("LONG", "SHORT"):
            rows = [r for r in rows if r.get("side") == side]
        min_score = request.args.get("min_score")
        if min_score:
            try:
                ms = int(min_score)
                rows = [r for r in rows if (r.get("score") or 0) >= ms]
            except ValueError:
                pass

        # Sort
        sort = (request.args.get("sort") or "dist").lower()
        if sort == "score":
            rows = sorted(rows, key=lambda r: (-(r.get("score") or 0), r.get("dist", 1)))
        elif sort == "vol_rank":
            rows = sorted(rows, key=lambda r: (-(r.get("vol_rank") or 0), r.get("dist", 1)))
        else:
            rows = sorted(rows, key=lambda r: r.get("dist", 1))

        limit = request.args.get("limit")
        if limit:
            try:
                rows = rows[:max(0, int(limit))]
            except ValueError:
                pass

        return jsonify({
            "results": rows,
            "warming": False,
            "stale": stale,
            "scanned_at": scanned_at,
            "near_pct": payload.get("near_pct"),
            "counts": payload.get("counts", {}),
            "total": len(rows),
        })

    @app.route("/api/swing-setup")
    def api_swing_setup():
        """Compute a front-side options debit-spread setup.

        Public read endpoint (no auth) — matches the pattern of other
        mobile-callable bot endpoints like /api/risk/account-type. The
        underlying analyzer only reads market data (Polygon + Schwab)
        and returns a setup spec; it doesn't touch user-scoped state
        or place orders.

        Query params:
          ticker        — SPY / QQQ / IWM / SPX / NDX
          mode          — scalp | intraday | swing
          max_risk_usd  — optional; defaults to 200 (mobile passes
                          user's per-symbol risk once Settings wires it)

        Cached server-side via Redis for 60s per (ticker, mode, risk)
        to avoid hammering Polygon + Schwab on rapid mode switches.
        """
        ticker = (request.args.get("ticker") or "").upper()
        mode = (request.args.get("mode") or "swing").lower()
        if not ticker:
            return jsonify({"error": "ticker required"}), 400
        if mode not in ("scalp", "intraday", "swing"):
            return jsonify({"error": f"unknown mode {mode!r}"}), 400

        max_risk_usd = request.args.get("max_risk_usd")
        if max_risk_usd:
            try:
                max_risk_usd = float(max_risk_usd)
            except ValueError:
                return jsonify({"error": "max_risk_usd must be numeric"}), 400
        else:
            max_risk_usd = 200.0

        import redis as _redis, hashlib
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        # Fold the MTF tuning config into the cache key so a Settings change
        # (stop/proximity/R:R) busts the 60s cache immediately instead of
        # lagging up to a minute.
        from lumisignals import mtf_config as _mtfc
        _cfgsig = json.dumps(_mtfc.get_config(), sort_keys=True)
        cache_key = "swing_setup:" + hashlib.sha1(
            f"{ticker}:{mode}:{max_risk_usd}:{_cfgsig}".encode()
        ).hexdigest()[:16]
        cached = rdb.get(cache_key)
        if cached:
            return jsonify(json.loads(cached))

        try:
            from lumisignals.swing_setup import compute_setup
            setup = compute_setup(ticker, mode, max_risk_usd)
        except Exception as e:
            logger.error("swing_setup compute failed: %s", e)
            return jsonify({"error": f"setup compute failed: {e}"}), 500

        # Bundle the chart URL so mobile can render the WebView directly
        # without re-deriving the params (entry/stop/target only present
        # in the shares spec; for options we overlay strikes + breakeven).
        chart_overlay = {}
        if setup.get("options"):
            opt = setup["options"]
            chart_overlay = {
                "long_strike": opt.get("long_strike"),
                "short_strike": opt.get("short_strike"),
                "breakeven": opt.get("breakeven"),
                "trigger_level": setup.get("trigger_level"),
            }
        setup["chart_overlay"] = chart_overlay

        # All-TF zones (D1/D2/S1/S2 per timeframe) — single source of truth
        # for the Dashboard panel's zones bar. Uses the SAME find_untouched_levels
        # call as the analyzer's trigger_level so chart entry == panel D1.
        # The panel reads this from the swing-setup response instead of
        # making a separate /api/mobile/compare/levels call.
        zones_by_tf = {}
        massive_key = os.environ.get("MASSIVE_API_KEY", "")
        if massive_key:
            try:
                from lumisignals.massive_client import get_shared_client
                from lumisignals.untouched_levels import (
                    find_htf_levels, HTF_TF_LOOKBACK)
                _massive = get_shared_client(massive_key)
                INDEX_SYMBOLS = {"SPX", "NDX", "RUT", "VIX", "DJI", "XSP", "XND"}
                is_forex = (len(ticker) == 6 and ticker[:3].isalpha()
                            and ticker[3:].isalpha() and ticker not in ("GOOGL",))
                if is_forex:
                    poly_ticker = f"C:{ticker}"
                elif ticker in INDEX_SYMBOLS:
                    poly_ticker = f"I:{ticker}"
                else:
                    poly_ticker = ticker
                # Deep per-TF lookback so the panel's zones match the Pine/TV
                # levels (same find_htf_levels the compare SRV column uses).
                tf_specs = [
                    ("1mo", "M"),  ("1w",  "W"),
                    ("1d",  "D"),  ("4h",  "4H"),
                    ("1h",  "1H"), ("30m", "30M"),
                    ("15m", "15M"),
                ]
                for tf_key, tf_label in tf_specs:
                    try:
                        lb = HTF_TF_LOOKBACK.get(tf_key, 50)
                        candles = _massive.get_candles(poly_ticker, tf_key, lb + 5)
                        if not candles or len(candles) < 3:
                            continue
                        price = candles[-1].close
                        highs = [c.high for c in reversed(candles)]
                        lows = [c.low for c in reversed(candles)]
                        s1, s2, d1, d2 = find_htf_levels(
                            highs, lows, price, lookback=lb)
                        recent_highs = [c.high for c in candles[-12:]]
                        recent_lows = [c.low for c in candles[-12:]]
                        zones_by_tf[tf_label] = {
                            "supply": s1, "supply2": s2,
                            "demand": d1, "demand2": d2,
                            "range_high": max(recent_highs) if recent_highs else None,
                            "range_low": min(recent_lows) if recent_lows else None,
                        }
                    except Exception as _e:
                        logger.debug("zones_by_tf err %s %s: %s", ticker, tf_key, _e)
            except Exception as e:
                logger.warning("zones_by_tf compute failed: %s", e)
        # Critical: override the analyzer's top-TF entry in zones_by_tf
        # with the EXACT zones the analyzer's _pick_trigger_level computed.
        # Without this, the endpoint's separate Polygon fetch can return a
        # slightly different last-bar low → different D1/D2 than what the
        # chart's trigger_level was derived from. Observed 2026-06-02 on
        # SCALP/SPY: chart entry 755.87 but panel 1H D1 757.73 / D2 756.78.
        top_tf_key = setup.get("top_tf_key")
        top_zones = setup.get("top_zones") or {}
        tf_key_to_label = {
            "3mo": "Q", "1mo": "M", "1w": "W", "1d": "D",
            "4h": "4H", "1h": "1H", "30m": "30M", "15m": "15M", "5m": "5M",
        }
        if top_tf_key and top_zones.get("demand") is not None:
            label = tf_key_to_label.get(top_tf_key, top_tf_key.upper())
            existing = zones_by_tf.get(label, {})
            zones_by_tf[label] = {
                "supply":  top_zones.get("supply"),
                "supply2": top_zones.get("supply2"),
                "demand":  top_zones.get("demand"),
                "demand2": top_zones.get("demand2"),
                # Preserve range numbers if we'd computed them
                "range_high": existing.get("range_high"),
                "range_low":  existing.get("range_low"),
            }
        setup["zones_by_tf"] = zones_by_tf

        rdb.setex(cache_key, 60, json.dumps(setup, default=str))
        return jsonify(setup)

    @app.route("/api/option-spread/order", methods=["POST"])
    def api_option_spread_order():
        """Place an atomic options debit spread via IB CPAPI combo.

        Auth: X-Sync-Key header (matches /api/positions/close pattern;
        mobile passes EXPO_PUBLIC_LUMI_SYNC_KEY env).

        Body: {
          ticker, direction ("BUY"|"SELL"), spread_type ("call_debit"|"put_debit"),
          expiry ("YYYY-MM-DD"), long_strike, short_strike, contracts,
          limit_price (net debit), max_risk_usd
        }

        Gated on Redis `equity:orders_enabled=1` (off by default).
        Risk gates in order: reconcile_gate → kill_switch → runaway_guard
        → cooldown. Then looks up conids, builds the combo, submits.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401

        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

        # Feature flag
        if not rdb.get("equity:orders_enabled"):
            return jsonify({
                "status": "skipped", "reason": "equity_orders_disabled",
            }), 503

        body = request.get_json(silent=True) or {}
        ticker = (body.get("ticker") or "").upper()
        direction = (body.get("direction") or "").upper()
        spread_type = body.get("spread_type") or ""
        expiry = body.get("expiry") or ""
        long_strike = body.get("long_strike")
        short_strike = body.get("short_strike")
        contracts = int(body.get("contracts") or 0)
        limit_price = body.get("limit_price")
        max_risk_usd = float(body.get("max_risk_usd") or 200)
        # Dashboard mode (scalp/intraday/mtf) — used to tag the strat_pos
        # so the mobile reconciler shows the right bucket. Missing → empty.
        mode = (body.get("mode") or "").lower()

        missing = [k for k, v in (
            ("ticker", ticker), ("direction", direction),
            ("spread_type", spread_type), ("expiry", expiry),
            ("long_strike", long_strike), ("short_strike", short_strike),
            ("contracts", contracts), ("limit_price", limit_price),
        ) if not v]
        if missing:
            return jsonify({"error": "missing fields: " + ",".join(missing)}), 400

        # Risk gates (mirror ORB Phase 9 pattern; share state with futures)
        try:
            from lumisignals import reconcile_gate
            if reconcile_gate.is_locked():
                return jsonify({"status": "skipped",
                                "reason": "reconcile_gate_locked"}), 503
        except Exception as e:
            logger.warning("reconcile_gate check failed (fail-closed): %s", e)
            return jsonify({"status": "skipped",
                            "reason": "reconcile_gate_check_failed"}), 503

        try:
            from lumisignals import kill_switch
            if kill_switch.is_blocking_entry():
                st = kill_switch.get_state()
                return jsonify({
                    "status": "skipped", "reason": "kill_switch_tripped",
                    "day_pnl": round(st.get("day_pnl", 0.0), 2),
                }), 200
        except Exception as e:
            logger.warning("kill switch check failed (fail-open): %s", e)

        try:
            from lumisignals import runaway_guard
            if runaway_guard.is_blocking_entry("swing_setup"):
                st = runaway_guard.get_state("swing_setup")
                return jsonify({
                    "status": "skipped", "reason": "runaway_guard_tripped",
                    "trip_reason": st.get("trip_reason"),
                }), 200
        except Exception as e:
            logger.warning("runaway_guard check failed (fail-open): %s", e)

        try:
            from lumisignals import cooldown
            if cooldown.is_active("swing_setup", ticker):
                return jsonify({
                    "status": "skipped", "reason": "cooldown_active",
                    "ttl_seconds": cooldown.ttl("swing_setup", ticker),
                }), 200
        except Exception as e:
            logger.warning("cooldown check failed (fail-open): %s", e)

        # Look up conids for both option legs via IB CPAPI
        try:
            from lumisignals.ibkr_cpapi import CPAPIClient
            client = CPAPIClient()
            client.ensure_session()
        except Exception as e:
            return jsonify({"error": f"CPAPI session failed: {e}"}), 503

        right = "C" if spread_type == "call_debit" else "P"
        long_conid = _lookup_option_conid_simple(client, ticker, expiry, long_strike, right)
        short_conid = _lookup_option_conid_simple(client, ticker, expiry, short_strike, right)
        if not (long_conid and short_conid):
            return jsonify({
                "error": "conid lookup failed",
                "long_conid": long_conid, "short_conid": short_conid,
            }), 502

        # Build the atomic combo: long leg BUY +1, short leg SELL -1.
        # Positive limit_price = pay debit.
        import uuid as _uuid
        coid = f"lumi_swing_{_uuid.uuid4().hex[:12]}"
        payload = client.build_combo_order(
            legs=[(long_conid, "BUY", 1), (short_conid, "SELL", 1)],
            quantity=contracts,
            limit_price=abs(float(limit_price)),
            order_type="LMT", tif="DAY", coid=coid,
        )

        # Diary INTENT_OPEN per leg before submit (best-effort)
        try:
            from lumisignals import diary
            for leg_label, conid, side, strike in (
                ("long",  long_conid,  "BUY",  long_strike),
                ("short", short_conid, "SELL", short_strike),
            ):
                diary.record_event(
                    broker="ib", strategy_id="swing_setup", ticker=ticker,
                    state=diary.State.INTENT_OPEN,
                    client_intent_id=f"{coid}_{leg_label}",
                    expected_qty=contracts,
                    meta={"coid": coid, "leg": leg_label, "conid": conid,
                          "strike": strike, "side": side,
                          "expiry": expiry, "spread_type": spread_type},
                )
        except Exception as e:
            logger.warning("diary INTENT_OPEN failed: %s", e)

        try:
            result = client.place_order(payload)
            # Tag perm_id → strategy for reconciler labeling.
            try:
                from lumisignals.ibkr_sync_cpapi import record_strategy_for_perm
                record_strategy_for_perm(result, "swing_setup")
            except Exception as _e:
                logger.debug("record_strategy_for_perm (swing combo) failed: %s", _e)
            # Tag perm_id → model (scalp/intraday/mtf) so the reconciler
            # can stash it on the strat_pos metadata when adopting. Mirrors
            # record_strategy_for_perm — 24h TTL covers same-day adoption.
            if mode:
                try:
                    import redis as _redis
                    _rdb_m = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
                    perm_ids = []
                    cands = result if isinstance(result, list) else [result]
                    for c in cands:
                        if isinstance(c, dict):
                            oid = c.get("order_id") or c.get("orderId")
                            if oid:
                                perm_ids.append(str(oid))
                    for pid in perm_ids:
                        _rdb_m.setex(f"ibkr:model_by_perm:{pid}", 86400, mode)
                except Exception as _e:
                    logger.debug("model_by_perm setex failed: %s", _e)
        except Exception as e:
            logger.error("swing combo place_order error: %s", e)
            return jsonify({"error": f"place_order failed: {e}",
                            "payload": payload}), 502

        # Extract order_id (combo single order, may need reply-walk)
        order_id = None
        if isinstance(result, list) and result:
            row = result[0]
            order_id = row.get("order_id") or row.get("orderId")
        elif isinstance(result, dict):
            order_id = result.get("order_id") or result.get("orderId")

        if not order_id:
            return jsonify({"status": "rejected",
                            "response": result,
                            "payload_coid": coid}), 502

        # Per-strategy runaway counter (swing_setup has its own cap,
        # so HTF FX losses don't bleed into it).
        try:
            runaway_guard.record_entry("swing_setup")
        except Exception:
            pass

        return jsonify({
            "status": "queued", "strategy": "swing_setup",
            "ticker": ticker, "direction": direction,
            "spread_type": spread_type,
            "contracts": contracts,
            "long_strike": long_strike, "short_strike": short_strike,
            "limit_price": limit_price,
            "expiry": expiry,
            "order_id": str(order_id),
            "coid": coid,
        })

    @app.route("/api/option-spread/close", methods=["POST"])
    def api_option_spread_close():
        """Close an open option spread at market via reverse combo.

        Auth: X-Sync-Key header (matches the order endpoint).

        Body: {
          ticker, spread_type, expiry, long_strike, short_strike,
          contracts, coid (original)
        }
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401

        body = request.get_json(silent=True) or {}
        ticker = (body.get("ticker") or "").upper()
        spread_type = body.get("spread_type") or ""
        expiry = body.get("expiry") or ""
        long_strike = body.get("long_strike")
        short_strike = body.get("short_strike")
        contracts = int(body.get("contracts") or 0)
        orig_coid = body.get("coid") or ""

        if not all([ticker, spread_type, expiry, long_strike, short_strike, contracts]):
            return jsonify({"error": "missing fields"}), 400

        try:
            from lumisignals.ibkr_cpapi import CPAPIClient
            client = CPAPIClient()
            client.ensure_session()
        except Exception as e:
            return jsonify({"error": f"CPAPI session failed: {e}"}), 503

        right = "C" if spread_type == "call_debit" else "P"
        long_conid = _lookup_option_conid_simple(client, ticker, expiry, long_strike, right)
        short_conid = _lookup_option_conid_simple(client, ticker, expiry, short_strike, right)
        if not (long_conid and short_conid):
            return jsonify({"error": "conid lookup failed for close"}), 502

        # Reverse the legs (SELL the long, BUY the short) at MKT
        import uuid as _uuid
        close_coid = f"lumi_swing_close_{_uuid.uuid4().hex[:12]}"
        payload = client.build_combo_order(
            legs=[(long_conid, "SELL", 1), (short_conid, "BUY", 1)],
            quantity=contracts, limit_price=0.0,
            order_type="MKT", tif="DAY", coid=close_coid,
        )

        try:
            from lumisignals import diary
            diary.record_event(
                broker="ib", strategy_id="swing_setup", ticker=ticker,
                state=diary.State.INTENT_CLOSE,
                client_intent_id=close_coid,
                meta={"orig_coid": orig_coid, "expiry": expiry,
                      "spread_type": spread_type, "contracts": contracts},
            )
        except Exception:
            pass

        try:
            result = client.place_order(payload)
        except Exception as e:
            return jsonify({"error": f"close place_order failed: {e}"}), 502

        order_id = None
        if isinstance(result, list) and result:
            order_id = result[0].get("order_id") or result[0].get("orderId")
        elif isinstance(result, dict):
            order_id = result.get("order_id") or result.get("orderId")

        return jsonify({
            "status": "queued" if order_id else "rejected",
            "order_id": str(order_id) if order_id else None,
            "coid": close_coid,
            "response": result if not order_id else None,
        })

    def _lookup_option_conid_simple(client, ticker, expiry_iso, strike, right):
        """Find an option conid via IB CPAPI /iserver/secdef/info.

        expiry_iso: "YYYY-MM-DD". Prefers SPXW class for SPX (avoids the
        AM-settled 3rd-Friday SPX). Returns int conid or None."""
        try:
            results = client.search_contract(ticker, "IND") or []
        except Exception:
            results = []
        if not results:
            results = client.search_contract(ticker, "STK") or []
        if not results:
            return None
        underlying_conid = results[0].get("conid")
        if not underlying_conid:
            return None
        expiry_compact = expiry_iso.replace("-", "")  # YYYYMMDD
        month = expiry_compact[:6]
        sec_def = client._request("GET", "/iserver/secdef/info", params={
            "conid": underlying_conid, "sectype": "OPT",
            "month": month, "strike": strike, "right": right,
            "exchange": "SMART",
        })
        if not (isinstance(sec_def, list) and sec_def):
            return None
        preferred = "SPXW" if ticker == "SPX" else None
        if preferred:
            for opt in sec_def:
                if (str(opt.get("maturityDate", "")).replace("-", "") == expiry_compact
                        and float(opt.get("strike", 0)) == float(strike)
                        and opt.get("tradingClass") == preferred):
                    return opt.get("conid")
        for opt in sec_def:
            if (str(opt.get("maturityDate", "")).replace("-", "") == expiry_compact
                    and float(opt.get("strike", 0)) == float(strike)):
                return opt.get("conid")
        return sec_def[0].get("conid")

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
        # Hard #5 (audit): restart-safety gate. Refuse mobile-initiated
        # orders until ibkr-sync has completed at least one reconcile pass
        # — same gate applied to the TV webhook futures path. Without this,
        # a spread order submitted from mobile right after a bot restart
        # could land on top of stale strat_pos / diary state.
        try:
            from lumisignals import reconcile_gate
            if reconcile_gate.is_locked():
                state = reconcile_gate.get_state()
                logger.warning("reconcile_gate BLOCKED mobile spread order: status=%s",
                               state.get("status"))
                return jsonify({
                    "status": "skipped",
                    "reason": "reconcile_gate_locked",
                    "gate_status": state.get("status"),
                    "gate_reason": state.get("reason"),
                }), 503
        except Exception as e:
            logger.warning("reconcile_gate check failed (fail-closed): %s", e)
            return jsonify({
                "status": "skipped",
                "reason": "reconcile_gate_check_failed",
            }), 503
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

    @app.route("/api/ibkr/mes-2n20/source", methods=["GET", "POST"])
    def api_mes_2n20_source():
        """Read/set the native-vs-TradingView source for the MES 2n20 strategy,
        and read the recent shadow-signal log. Sync-key authed.

        GET  → {source, shadow: [recent signals]}
        POST {source: tradingview|shadow|native|off} → sets the flag.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        if request.method == "POST":
            new = (request.get_json(silent=True) or {}).get("source", "").strip().lower()
            if new not in ("tradingview", "shadow", "native", "off"):
                return jsonify({"error": "source must be tradingview|shadow|native|off"}), 400
            rdb.set("ibkr:mes_2n20:source", new)
            logger.info("MES 2n20 source set to %s", new)
        cur = rdb.get("ibkr:mes_2n20:source")
        signals = [json.loads(x) for x in rdb.lrange("ibkr:mes_2n20:native", 0, 49)]
        return jsonify({
            "source": cur.decode() if cur else "tradingview",
            "signals": signals,
        })

    @app.route("/api/ibkr/mes-2n20/parity")
    def api_mes_2n20_parity():
        """Compare the native 2n20 signal stream against the TradingView alert
        stream, aligned by bar (tolerant ±1 bar / same direction). Sync-key
        authed. Shows agree / mismatch / native-only / tv-only so you can
        confirm parity without eyeballing TradingView."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        tv = [json.loads(x) for x in rdb.lrange("ibkr:mes_2n20:tv", 0, 99)]
        native = [json.loads(x) for x in rdb.lrange("ibkr:mes_2n20:native", 0, 99)]

        def _bt(rec):
            try:
                return int(rec.get("bar_time") or 0)
            except (TypeError, ValueError):
                return 0

        TOL = 120  # one 2m bar of slack between the two streams' bar stamps
        used = set()
        rows = []
        for n in native:
            nbt, ndir = _bt(n), n.get("direction")
            match = None
            for i, t in enumerate(tv):
                if i in used:
                    continue
                # same kind/direction within ±1 bar
                same_dir = (t.get("direction") == ndir) or (
                    n.get("kind") == "EXIT" and t.get("kind") == "EXIT")
                if same_dir and abs(_bt(t) - nbt) <= TOL:
                    match = i
                    break
            if match is not None:
                used.add(match)
            rows.append({
                "bar_time": nbt, "kind": n.get("kind"), "native_dir": ndir,
                "tv_dir": tv[match].get("direction") if match is not None else None,
                "native_traded": n.get("traded"),
                "status": "agree" if match is not None else "native_only",
            })
        # TV alerts with no native match
        for i, t in enumerate(tv):
            if i not in used:
                rows.append({
                    "bar_time": _bt(t), "kind": t.get("kind"),
                    "native_dir": None, "tv_dir": t.get("direction"),
                    "native_traded": False, "status": "tv_only",
                })
        rows.sort(key=lambda r: r["bar_time"], reverse=True)
        agree = sum(1 for r in rows if r["status"] == "agree")
        return jsonify({
            "summary": {
                "agree": agree, "native_only": sum(1 for r in rows if r["status"] == "native_only"),
                "tv_only": sum(1 for r in rows if r["status"] == "tv_only"),
                "native_total": len(native), "tv_total": len(tv),
            },
            "rows": rows[:60],
        })

    @app.route("/api/ibkr/orb/source", methods=["GET", "POST"])
    def api_orb_source():
        """Read/set the native-vs-TradingView source for ORB, and read the
        recent native triggers. Sync-key authed."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        if request.method == "POST":
            new = (request.get_json(silent=True) or {}).get("source", "").strip().lower()
            if new not in ("tradingview", "shadow", "native", "off"):
                return jsonify({"error": "source must be tradingview|shadow|native|off"}), 400
            rdb.set("ibkr:orb:source", new)
            logger.info("ORB source set to %s", new)
        cur = rdb.get("ibkr:orb:source")
        native = [json.loads(x) for x in rdb.lrange("ibkr:orb:native", 0, 19)]
        return jsonify({"source": cur.decode() if cur else "tradingview", "native": native})

    @app.route("/api/ibkr/orb/parity")
    def api_orb_parity():
        """ORB native trigger stream vs the TradingView ORB alert stream.
        ORB fires at most ~2x/day in the morning, so we just return both
        streams (newest first) rather than bar-aligning. Sync-key authed."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "Invalid sync key"}), 403
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        native = [json.loads(x) for x in rdb.lrange("ibkr:orb:native", 0, 49)]
        tv = [json.loads(x) for x in rdb.lrange("ibkr:orb:tv", 0, 49)]
        return jsonify({
            "summary": {"native_total": len(native), "tv_total": len(tv)},
            "native": native, "tv": tv,
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

                # Backfill derived fields server-side so every caller
                # benefits without each one having to recompute. Closed-
                # trade rows have been arriving with duration_mins / RR
                # null even when entry, stop, and exit are all known.
                entry_p = data.get("entry_price", 0) or 0
                exit_p = data.get("exit_price", 0) or 0
                stop_p = data.get("stop_loss") or 0
                target_p = data.get("take_profit") or 0

                opened_s = data.get("opened_at", "")
                closed_s = data.get("closed_at", "")
                duration_mins = data.get("duration_mins")
                if duration_mins is None and opened_s and closed_s:
                    try:
                        _o = datetime.fromisoformat(opened_s.replace("Z", "+00:00"))
                        _c = datetime.fromisoformat(closed_s.replace("Z", "+00:00"))
                        # Column is INTEGER — must cast.
                        duration_mins = int(round((_c - _o).total_seconds() / 60))
                    except Exception:
                        duration_mins = None

                planned_rr = data.get("planned_rr")
                achieved_rr = data.get("achieved_rr")
                # Risk = |entry - stop|; planned reward = |target - entry|;
                # achieved reward = |exit - entry|. Sign-agnostic ratio.
                if entry_p and stop_p:
                    risk = abs(entry_p - stop_p)
                    if risk:
                        if planned_rr is None and target_p:
                            planned_rr = round(abs(target_p - entry_p) / risk, 2)
                        if achieved_rr is None and exit_p:
                            achieved_rr = round((exit_p - entry_p) / risk
                                                * (1 if str(data.get("direction", "")).upper() in ("LONG", "BUY")
                                                   else -1), 2)

                record_closed_trade(user_id, {
                    "id": trade_id,
                    "broker": "ib",
                    "asset_type": asset_type,
                    "instrument": data.get("ticker", data.get("symbol", "")),
                    "direction": data.get("direction", ""),
                    "contracts": data.get("contracts", 1),
                    "entry_price": entry_p,
                    "exit_price": exit_p,
                    "realized_pl": data.get("realized_pnl", 0),
                    "stop_loss": data.get("stop_loss"),
                    "take_profit": data.get("take_profit"),
                    "planned_rr": planned_rr,
                    "achieved_rr": achieved_rr,
                    "strategy": data.get("strategy", ""),
                    "model": data.get("model", ""),
                    "close_reason": data.get("close_reason", ""),
                    "won": (data.get("realized_pnl", 0) or 0) > 0,
                    "spread_type": data.get("spread_type"),
                    "sell_strike": data.get("sell_strike"),
                    "buy_strike": data.get("buy_strike"),
                    "opened_at": opened_s,
                    "closed_at": closed_s,
                    "duration_mins": duration_mins,
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

    @app.route("/api/positions/audit")
    def api_positions_audit():
        """IB vs Bot reconciliation. For each open IB position, compare
        IB's actual quantity against the sum of per-strategy strat_pos
        coverage. Surface mismatches (orphan / phantom / matched).
        """
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

        # Read latest IB snapshot from the sync's Redis cache
        ib_raw = rdb.get("ibkr:data:1")
        if not ib_raw:
            return jsonify({"ok": False, "error": "no IB snapshot", "last_synced": None})
        ib = json.loads(ib_raw)

        # Build per-instrument summary — include ALL asset classes
        # (FUT, STK, OPT, etc.) so the user can verify the full IB
        # state at a glance, not just the strategies the bot tracks.
        rows = []

        # Detected spreads from the sync's _detect_spreads — pair option
        # legs into single rows so a 2-spread account shows as 2 rows,
        # not 4 confusing single-leg rows that look like phantom orphans.
        # Build a set of leg signatures that are part of a detected
        # spread so we can skip those legs when iterating positions.
        spreads_in = ib.get("spreads", []) or []
        legs_in_spreads = set()
        for sp in spreads_in:
            for strike_field in ("long_strike", "short_strike"):
                strike = sp.get(strike_field)
                if strike:
                    legs_in_spreads.add((
                        sp.get("symbol", ""),
                        sp.get("expiration", ""),
                        sp.get("right", ""),
                        float(strike),
                    ))

        ib_positions = {}  # key → {qty, avg_cost, sec_type, label, ...}
        for p in ib.get("positions", []):
            sym = p.get("symbol")
            sec_type = p.get("sec_type", "?")
            if not sym:
                continue
            # Skip option legs that are already counted in a detected spread.
            if sec_type == "OPT":
                leg_key = (
                    sym,
                    p.get("expiration", ""),
                    p.get("right", ""),
                    float(p.get("strike", 0)),
                )
                if leg_key in legs_in_spreads:
                    continue
            # Options get description-keyed (separate legs) since one symbol
            # can have many option contracts. Other types key by symbol.
            if sec_type == "OPT":
                key = f"{sym} {p.get('description', '')[:30]}"
            else:
                key = sym
            ib_positions[key] = {
                "symbol": sym,
                "qty": int(p.get("quantity", 0)),
                "avg_cost": float(p.get("avg_cost", 0)) / float(p.get("multiplier", 1) or 1),
                "market_price": float(p.get("market_price", 0)),
                "unrealized_pl": float(p.get("unrealized_pnl", 0)),
                "sec_type": sec_type,
                "multiplier": float(p.get("multiplier", 1)),
                "description": p.get("description", ""),
            }

        # Emit one synthetic row per detected spread. Spreads aren't
        # tracked in strat_pos today, so they'll classify as ALL ORPHAN
        # until a future change registers them. ib_qty uses contract
        # count (always positive), avg uses per-spread net cost (debit
        # paid or credit received).
        for sp in spreads_in:
            sym = sp.get("symbol", "")
            spread_type = sp.get("spread_type", "Spread")
            long_strike = sp.get("long_strike", 0)
            short_strike = sp.get("short_strike", 0)
            qty = int(sp.get("quantity", 0) or 0)
            if not sym or qty <= 0:
                continue
            label = f"{spread_type} {long_strike:g}/{short_strike:g}"
            key = f"{sym} OPT {label}"
            ib_positions[key] = {
                "symbol": sym,
                "qty": qty,
                "avg_cost": float(sp.get("net_cost", 0)),
                "market_price": float(sp.get("current_value", 0)) / max(qty, 1),
                "unrealized_pl": float(sp.get("unrealized_pnl", 0)),
                "sec_type": "OPT",
                "multiplier": 100.0,
                "description": label,
                # Structured fields for the mobile UI to render an IBKR-style
                # vertical descriptor (e.g. "VERTICAL SPX 100 2 JUN 26 (0) 7610/7615 C")
                "expiration": str(sp.get("expiration", "")),  # YYYYMMDD
                "right": str(sp.get("right", "")),            # "C" or "P"
                "long_strike": float(long_strike or 0),
                "short_strike": float(short_strike or 0),
                "spread_type": spread_type,
                # Per-spread max profit + max risk (dollars). Mobile multiplies
                # by qty to show "uPL +$X / $Y max" progress vs the target.
                "max_profit": float(sp.get("max_profit", 0)),
                "max_risk": float(sp.get("max_risk", 0)),
            }

        # Gather strat_pos coverage per symbol
        strat_by_symbol = {}  # symbol → [strat_pos dicts]
        try:
            for k in rdb.scan_iter("ibkr:strat_pos:*"):
                raw = rdb.get(k)
                if not raw:
                    continue
                sp = json.loads(raw)
                sym = sp.get("ticker", "")
                if not sym:
                    continue
                strat_by_symbol.setdefault(sym, []).append({
                    "strategy": sp.get("strategy", ""),
                    "direction": sp.get("direction", ""),
                    "contracts": int(sp.get("contracts", 0)),
                    "entry_price": float(sp.get("entry_price", 0)),
                    "perm_id": str(sp.get("perm_id", "")),
                    "opened_at": sp.get("opened_at", ""),
                    # Model lets the mobile UI show whether a bot trade came
                    # from Scalp / Intraday / Swing. Pine signals stash it in
                    # metadata.model; manual + reconciler-adopted strat_pos
                    # records don't have it and render no badge.
                    "model": str((sp.get("metadata") or {}).get("model", "")),
                })
        except Exception as e:
            logger.warning("audit strat_pos read failed: %s", e)

        # Index filled_orders by symbol so we can attach the last
        # handful of fills to any mismatch row. The sync's _collect_data
        # already puts execution rows here with symbol/side/qty/price/
        # time/order_id (which is order_ref when tagged, execution_id
        # when not). Sort newest-first by time. Time comes in as a
        # millisecond unix string in most cases — handle both.
        def _fill_ts_ms(f):
            t = f.get("time") or 0
            try:
                t = int(t)
            except (TypeError, ValueError):
                return 0
            # Heuristic: > year-3000 in seconds means it's already ms
            return t if t > 32000000000 else t * 1000
        fills_by_symbol = {}
        for f in ib.get("filled_orders", []) or []:
            sym = f.get("symbol", "")
            if not sym:
                continue
            fills_by_symbol.setdefault(sym, []).append(f)
        for sym in fills_by_symbol:
            fills_by_symbol[sym].sort(key=_fill_ts_ms, reverse=True)

        def _classify_fill(ref):
            """Tag each fill with its source for the mobile UI."""
            if not ref or ref == 0 or ref == "0":
                return "untagged"
            ref_s = str(ref)
            if ref_s.startswith("lumi_"):
                # Bracket children carry the parent ref + "sl"/"tp" suffix
                if ref_s.endswith("sl"):
                    return "bracket_stop"
                if ref_s.endswith("tp"):
                    return "bracket_target"
                # Strip "lumi_" prefix and trailing 8-hex coid → strategy slug
                core = ref_s[5:]
                if "_" in core:
                    return f"bot:{core.rsplit('_', 1)[0]}"
                return f"bot:{core}"
            return "other"

        # Build the audit rows.
        # IB positions key on symbol (OPT keys differently); strat_pos
        # keys on ticker symbol. Join by symbol so OPT legs and tracked
        # futures positions both show up.
        #
        # Dedup: when an OPT synthetic row already exists for a symbol
        # (e.g. "AMZN OPT Put Debit Spread 250/255"), the corresponding
        # bare-symbol strat_pos key ("AMZN") would otherwise emit a
        # second row with no IB data and render as a misleading PHANTOM.
        # Drop the bare-symbol key in that case — the OPT row's strats
        # lookup will still find the strat_pos by symbol.
        covered_by_opt_synthetic = {
            v["symbol"] for v in ib_positions.values()
            if v.get("sec_type") == "OPT"
        }
        all_keys = set(ib_positions.keys()) | (
            set(strat_by_symbol.keys()) - covered_by_opt_synthetic
        )
        for key in sorted(all_keys):
            ib_data = ib_positions.get(key)
            # strats lookup uses the IB symbol field (or the key itself
            # if no IB data — e.g. phantom strat_pos with no IB row)
            lookup_sym = ib_data["symbol"] if ib_data else key
            strats = strat_by_symbol.get(lookup_sym, [])
            ib_qty = ib_data["qty"] if ib_data else 0
            # Signed tracked qty (BUY contributes +, SELL contributes -)
            tracked_signed = sum(
                sp["contracts"] if sp["direction"] == "BUY" else -sp["contracts"]
                for sp in strats
            )
            tracked_abs = sum(sp["contracts"] for sp in strats)
            orphan_qty = abs(ib_qty) - tracked_abs

            # OPT spreads: the bot's "direction" field stores BIAS (SELL=
            # bearish for a put debit, BUY=bullish for a put credit), not
            # the position sign — but you always BUY the combo, so IB
            # reports +N regardless. Skip the direction-mismatch check
            # for OPT and compare by absolute contracts instead.
            is_opt = bool(ib_data) and ib_data.get("sec_type") == "OPT"

            # Classify
            if ib_qty == 0 and tracked_abs == 0:
                status = "flat"; status_label = "FLAT"
            elif ib_qty == 0 and tracked_abs > 0:
                status = "phantom"; status_label = "PHANTOM (bot thinks open, IB shows flat)"
            elif ib_qty != 0 and tracked_abs == 0:
                status = "all_orphan"; status_label = "ALL ORPHAN (IB open, no strat_pos)"
            elif (not is_opt) and tracked_signed * (1 if ib_qty > 0 else -1) <= 0 and ib_qty != 0:
                # Tracked direction opposite to IB direction (non-OPT only)
                status = "direction_mismatch"; status_label = "DIRECTION MISMATCH"
            elif orphan_qty > 0:
                status = "partial_orphan"; status_label = f"PARTIAL ORPHAN ({orphan_qty} of {abs(ib_qty)} untracked)"
            elif orphan_qty < 0:
                status = "over_tracked"; status_label = f"OVER-TRACKED (bot has {tracked_abs}, IB only {abs(ib_qty)})"
            else:
                status = "matched"; status_label = "MATCHED"

            # For mismatch rows, attach the last few IB fills for this
            # symbol so the user can see what created the discrepancy
            # (manual order vs bracket child vs another strategy).
            recent_fills = []
            if status not in ("matched", "flat"):
                for f in (fills_by_symbol.get(lookup_sym, []) or [])[:6]:
                    ref = f.get("order_id")
                    recent_fills.append({
                        "time_ms": _fill_ts_ms(f),
                        "side": f.get("action") or "",
                        "qty": f.get("quantity") or 0,
                        "price": f.get("price") or 0,
                        "order_ref": str(ref) if ref else None,
                        "source": _classify_fill(ref),
                    })

            rows.append({
                "instrument": lookup_sym,
                "display_key": key,
                "asset_type": ib_data["sec_type"] if ib_data else "?",
                "description": ib_data["description"] if ib_data else "",
                # Structured option-spread fields (synthetic OPT rows only).
                # Mobile uses these to render an IBKR-style vertical line:
                #   "VERTICAL SPX 100 2 JUN 26 (0) 7610/7615 C"
                "expiration": ib_data.get("expiration", "") if ib_data else "",
                "right": ib_data.get("right", "") if ib_data else "",
                "long_strike": ib_data.get("long_strike", 0) if ib_data else 0,
                "short_strike": ib_data.get("short_strike", 0) if ib_data else 0,
                "spread_type": ib_data.get("spread_type", "") if ib_data else "",
                "multiplier": ib_data.get("multiplier", 0) if ib_data else 0,
                "max_profit": ib_data.get("max_profit", 0) if ib_data else 0,
                "max_risk": ib_data.get("max_risk", 0) if ib_data else 0,
                "ib_qty": ib_qty,
                "ib_avg": round(ib_data["avg_cost"], 4) if ib_data else None,
                "ib_market_price": round(ib_data["market_price"], 4) if ib_data else None,
                "ib_unrealized_pl": round(ib_data["unrealized_pl"], 2) if ib_data else None,
                "tracked_signed": tracked_signed,
                "tracked_abs": tracked_abs,
                "orphan_qty": orphan_qty,
                "strats": strats,
                "status": status,
                "status_label": status_label,
                "recent_fills": recent_fills,
            })

        # Total exposure summary for the "you are flat" confirmation
        net_long_count = sum(1 for r in rows if r["ib_qty"] > 0)
        net_short_count = sum(1 for r in rows if r["ib_qty"] < 0)

        return jsonify({
            "ok": True,
            "last_synced": ib.get("last_synced", ""),
            "rows": rows,
            "summary": {
                "total_positions": len(rows),
                "long_count": net_long_count,
                "short_count": net_short_count,
                "is_flat": (net_long_count == 0 and net_short_count == 0),
            },
        })

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

    @app.route("/api/strategies/regime")
    def api_strategies_regime():
        """Per-strategy regime state for each pair.

        Reads the state written by saas.regime_runner.recompute() from
        Redis (regime:{strategy}:{pair}).  The mobile Strategies tab
        polls this; the bot's entry path also gates on the same data.

        Now also lists strategies that don't have a regime filter
        (H1 Zone Scalp) so the tab can navigate to their charts.
        """
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        from saas.regime_runner import FX_4H_PAIRS, REDIS_KEY_PATTERN
        out_pairs = {}
        for pair in FX_4H_PAIRS:
            raw = rdb.get(REDIS_KEY_PATTERN.format(strategy="fx_4h", pair=pair))
            if not raw:
                continue
            try:
                state = json.loads(raw)
                out_pairs[pair] = state
            except Exception:
                continue
        eligible = sum(1 for s in out_pairs.values() if s.get("eligible"))

        # H1 Zone Scalp — no regime filter, but expose its universe + a
        # lightweight per-pair active-bundle count from Oanda so the tab
        # shows useful state. Heavy: this calls Oanda twice. Cache 30s in
        # Redis so multiple Strategies-tab opens don't hammer the broker.
        h1_zone_pairs: dict = {}
        try:
            from lumisignals.fx_h1_zone_scalp import DEFAULT_PAIRS as H1Z_PAIRS
            cached = rdb.get("api:h1_zone:strategies_summary")
            if cached:
                h1_zone_pairs = json.loads(cached)
            else:
                # Fresh fetch
                import psycopg2
                with psycopg2.connect(os.environ.get(
                    "DATABASE_URL",
                    "postgresql://lumisignals:LumiBot2026@localhost/lumisignals_db",
                )) as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT oanda_api_key, oanda_account_id, oanda_environment "
                        "FROM users WHERE bot_active=true AND oanda_api_key IS NOT NULL "
                        "ORDER BY id LIMIT 1")
                    row = cur.fetchone()
                if row:
                    from lumisignals.oanda_client import OandaClient
                    key, acct, env = row
                    oa = OandaClient(account_id=acct, api_key=key,
                                     environment=env or "practice")
                    from collections import Counter
                    counts = Counter()
                    try:
                        pend = oa._request("GET", f"/v3/accounts/{acct}/pendingOrders")
                        for o in pend.get("orders", []):
                            tag = ((o.get("clientExtensions") or {}).get("tag") or "")
                            if not tag.startswith("scalp_h1zone:"): continue
                            parts = tag.split(":")
                            if len(parts) == 4:
                                counts[(parts[2], "pending")] += 1
                    except Exception:
                        pass
                    try:
                        opn = oa._request("GET", f"/v3/accounts/{acct}/openTrades")
                        for t in opn.get("trades", []):
                            tag = ((t.get("clientExtensions") or {}).get("tag") or "")
                            if not tag.startswith("scalp_h1zone:"): continue
                            parts = tag.split(":")
                            if len(parts) == 4:
                                counts[(parts[2], "filled")] += 1
                    except Exception:
                        pass
                    for p in H1Z_PAIRS:
                        h1_zone_pairs[p] = {
                            "pair": p,
                            "pending_legs": counts.get((p, "pending"), 0),
                            "filled_legs": counts.get((p, "filled"), 0),
                        }
                    rdb.setex("api:h1_zone:strategies_summary", 30,
                              json.dumps(h1_zone_pairs))
        except Exception as e:
            logger.debug("h1_zone strategies summary failed: %s", e)
            try:
                from lumisignals.fx_h1_zone_scalp import DEFAULT_PAIRS as H1Z_PAIRS
                for p in H1Z_PAIRS:
                    h1_zone_pairs[p] = {"pair": p, "pending_legs": 0, "filled_legs": 0}
            except Exception:
                H1Z_PAIRS = []

        # ── Tidewater (HTF Levels family) per-pair zone counts ──
        # No regime filter; per-pair card shows how many active zones
        # exist across the three durations (Scalp/Intraday/Swing) so the
        # user can see at a glance where the strategy is currently
        # watching. Pulls from the bot's per-model watchlist:1:{model}
        # Redis keys — same data the watchlist endpoint serves.
        tide_pairs: dict = {}
        try:
            FX_PAIRS = ["EUR_USD", "USD_JPY", "GBP_USD", "USD_CHF",
                        "AUD_USD", "USD_CAD", "NZD_USD"]
            for p in FX_PAIRS:
                tide_pairs[p] = {"pair": p,
                                  "hourly_zones": 0,   # scalp model
                                  "daily_zones": 0,    # intraday model
                                  "weekly_zones": 0,   # swing model
                                  "total_zones": 0}
            for model_key, duration_key in (("scalp", "hourly_zones"),
                                             ("intraday", "daily_zones"),
                                             ("swing", "weekly_zones")):
                raw = rdb.get(f"watchlist:1:{model_key}")
                if not raw:
                    continue
                zones = json.loads(raw)
                for z in zones:
                    inst = z.get("instrument") or ""
                    if inst in tide_pairs:
                        tide_pairs[inst][duration_key] += 1
                        tide_pairs[inst]["total_zones"] += 1
        except Exception as e:
            logger.debug("tidewater summary failed: %s", e)

        return jsonify({
            "strategies": {
                "fx_4h": {
                    "name": "Stillwater",
                    "subtitle": "FX Intraday 4H",
                    "description": (
                        "Trend continuation on 4-hour bars, restricted "
                        "to low-volatility pairs in range-bound regimes. "
                        "Enters when an overwhelm candle aligns with the "
                        "20 EMA, weekly VWAP, and monthly VWAP. "
                        "Stops at 1.5× ATR, targets 2:1 R:R, "
                        "$1,000 risk per trade."
                    ),
                    "universe": FX_4H_PAIRS,
                    "eligible_count": eligible,
                    "total_count": len(FX_4H_PAIRS),
                    "pairs": out_pairs,
                    "chart_strategy": "fx_4h",
                },
                "tidewater": {
                    "name": "Tidewater",
                    "subtitle": "Multi-TF zone scalp/intraday/swing",
                    "description": (
                        "Watches untouched supply/demand zones at three "
                        "durations — Scalp (1H zones, 5m trigger, 15m "
                        "direction gate), Intraday (1D zones, 15m "
                        "trigger, 1H direction gate), Swing (1mo zones, "
                        "1D trigger, 1W direction gate). Touch-to-"
                        "trigger on a zone tap; FX direction comes from "
                        "N=15 swing structure. Native Oanda SL/TP "
                        "brackets."
                    ),
                    "universe": list(tide_pairs.keys()),
                    "eligible_count": sum(
                        1 for p in tide_pairs.values()
                        if p["total_zones"] > 0),
                    "total_count": len(tide_pairs),
                    "pairs": tide_pairs,
                    "chart_strategy": "htf_levels",
                },
                "h1_zone": {
                    "name": "H1 Zone Scalp",
                    "subtitle": "FX 5m near H1 zones (paper)",
                    "description": (
                        "Limit-orders 2 pips inside H1 demand/supply zones "
                        "when the 5m setup aligns with higher-TF structure "
                        "direction. Each signal places 4 trades targeting "
                        "25/50/75/100% of the distance to the opposing "
                        "zone. Two trend filters run independently: α "
                        "(15m) and β (1h). $10 risk per leg, paper-only."
                    ),
                    "universe": list(H1Z_PAIRS),
                    "eligible_count": len(H1Z_PAIRS),
                    "total_count": len(H1Z_PAIRS),
                    "pairs": h1_zone_pairs,
                    "chart_strategy": "h1_zone",
                },
            },
        })

    @app.route("/api/strategies/signals")
    def api_strategies_signals():
        """Return every trade_events row matching the filters.

        Built for diffing the bot's signal stream against TradingView's
        alert log when counts disagree. JSON list, oldest first.

        Query params:
            strategy  — strategy_id, e.g. "futures_2n20" or "futures_2n20_v2" (optional)
            ticker    — e.g. "MES" (optional)
            since     — ISO timestamp inclusive lower bound (optional)
            until     — ISO timestamp exclusive upper bound (optional)
            limit     — max rows, default 500, max 5000
            format    — "json" (default) or "html" for a sortable browser view

        Auth: X-Sync-Key header.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401
        from lumisignals.diary import query_events, fetch_events_by_broker_ids
        strategy = request.args.get("strategy") or None
        ticker = (request.args.get("ticker") or "").upper().strip() or None
        since = request.args.get("since") or None
        until = request.args.get("until") or None
        try:
            limit = int(request.args.get("limit", 500))
        except ValueError:
            limit = 500
        rows = query_events(strategy_id=strategy, ticker=ticker,
                            since=since, until=until, limit=limit)

        # Enrich exit rows with entry_time + entry_price from the matching
        # OPEN event. Both signal-closes (CLOSED) and stop-outs (STOP_FIRED)
        # are exits, so the held-duration stamp applies to both. Entries on
        # overnight trades often happen outside the requested window, so a
        # fresh query by broker_trade_id is needed.
        _EXIT_STATES = ("CLOSED", "STOP_FIRED")
        # The entry side may be a clean OPEN or a reconciler-adopted fill
        # (RECONCILE_ADOPTED) — most futures_2n20 entries are adopted, so a
        # bare state="OPEN" lookup misses them (10/12 stops had no entry_time).
        _ENTRY_STATES = ("OPEN", "RECONCILE_ADOPTED")
        # An adopted entry is keyed "adopted:<order_id>" while its exit row is
        # keyed "<order_id>" — same trade, different spelling. Normalize to the
        # bare order id so they link, and query BOTH spellings so the fetch
        # actually returns the adopted entry rows.
        def _norm_btid(b):
            return (b or "").rsplit(":", 1)[-1]
        closed_ids = [r.get("broker_trade_id") for r in rows
                      if r.get("state") in _EXIT_STATES and r.get("broker_trade_id")]
        if closed_ids:
            lookup_ids = set()
            for cid in closed_ids:
                base = _norm_btid(cid)
                lookup_ids.update((cid, base, f"adopted:{base}"))
            entry_events = [o for o in fetch_events_by_broker_ids(list(lookup_ids))
                            if o.get("state") in _ENTRY_STATES and o.get("broker_trade_id")]
            # Prefer a true OPEN over an adopted fill, then the earliest.
            _rank = {"OPEN": 0, "RECONCILE_ADOPTED": 1}
            entry_events.sort(key=lambda o: (_rank.get(o.get("state"), 9),
                                             o.get("event_time") or ""))
            open_by_id: dict = {}
            for o in entry_events:
                nid = _norm_btid(o.get("broker_trade_id"))
                if nid and nid not in open_by_id:
                    open_by_id[nid] = o
            for r in rows:
                if r.get("state") in _EXIT_STATES:
                    m = open_by_id.get(_norm_btid(r.get("broker_trade_id")))
                    if m:
                        r["entry_time"] = m.get("event_time")
                        # If the exit row didn't carry the entry price
                        # itself, fall back to the OPEN's fill price.
                        if r.get("entry_price") is None and m.get("entry_price") is not None:
                            r["entry_price"] = m.get("entry_price")

        # Annotate each row with a "direction" parsed out of `reason`.
        # The reason field carries the TV-side signal label ("TV BUY [2n20]",
        # "TV CLOSE_SHORT [2n20]", "Red Takeout Green", etc.) — pull a clean
        # direction out so consumers don't have to re-parse.
        for r in rows:
            reason = (r.get("reason") or "").upper()
            if "CLOSE_LONG" in reason or "X-LONG" in reason:
                r["direction"] = "CLOSE_LONG"
            elif "CLOSE_SHORT" in reason or "X-SHORT" in reason:
                r["direction"] = "CLOSE_SHORT"
            elif " BUY" in reason or reason.startswith("BUY"):
                r["direction"] = "BUY"
            elif " SELL" in reason or reason.startswith("SELL"):
                r["direction"] = "SELL"
            else:
                r["direction"] = None

        fmt = request.args.get("format", "json").lower()
        if fmt != "html":
            return jsonify({
                "count": len(rows),
                "filters": {"strategy": strategy, "ticker": ticker,
                            "since": since, "until": until, "limit": limit},
                "events": rows,
            })

        # Tiny HTML view — sortable browser table for visual diff vs TV.
        def esc(v):
            from html import escape as _e
            return _e(str(v)) if v is not None else ""
        def color_for(state, direction):
            if state == "INTENT_OPEN" or state == "OPEN":
                return "#1b5e20" if direction == "BUY" else "#b71c1c"
            if state == "INTENT_CLOSE" or state == "CLOSED":
                return "#555"
            return "#777"
        head_filters = f"strategy={strategy or '*'} ticker={ticker or '*'} since={since or '*'} until={until or '*'}"
        body_rows = []
        for r in rows:
            color = color_for(r.get("state"), r.get("direction"))
            body_rows.append(
                "<tr>"
                + f"<td>{esc(r.get('event_time', '')[:19])}</td>"
                + f"<td>{esc(r.get('ticker'))}</td>"
                + f"<td style='color:{color}'>{esc(r.get('state'))}</td>"
                + f"<td>{esc(r.get('direction'))}</td>"
                + f"<td>{esc(r.get('entry_price'))}</td>"
                + f"<td>{esc(r.get('exit_price'))}</td>"
                + f"<td>{esc(r.get('stop_price'))}</td>"
                + f"<td>{esc(r.get('realized_pl'))}</td>"
                + f"<td>{esc(r.get('reason'))}</td>"
                + f"<td>{esc(r.get('broker_trade_id'))}</td>"
                + "</tr>"
            )
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Signals</title>"
            "<style>"
            "body{font:13px -apple-system,sans-serif;background:#fafafa;color:#222;padding:12px}"
            "h2{margin:0 0 8px;font-size:15px}"
            ".sub{color:#888;font-size:11px;margin-bottom:12px}"
            "table{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.06)}"
            "th,td{padding:6px 10px;border-bottom:1px solid #eee;text-align:left;white-space:nowrap}"
            "th{background:#f0f0f0;font-weight:600;font-size:12px}"
            "tr:hover{background:#fafcff}"
            "</style></head><body>"
            f"<h2>Signals · {len(rows)} events</h2>"
            f"<div class='sub'>{esc(head_filters)}</div>"
            "<table>"
            "<thead><tr><th>Time (UTC)</th><th>Ticker</th><th>State</th>"
            "<th>Dir</th><th>Entry</th><th>Exit</th><th>Stop</th><th>P&amp;L</th>"
            "<th>Reason</th><th>Broker ID</th></tr></thead>"
            "<tbody>" + "".join(body_rows) + "</tbody></table>"
            "</body></html>"
        )
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    @app.route("/api/risk/kill-switch", methods=["GET", "PUT"])
    def api_risk_kill_switch():
        """Read or update the daily-loss kill switch.

        GET  → { config, state }
        PUT  → body: any subset of { enabled, threshold_usd, reset_hour_et,
                                      reset_minute_et }
                returns the new merged config + recomputed state.
        Auth: X-Sync-Key header.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401
        from lumisignals import kill_switch
        if request.method == "PUT":
            body = request.get_json(silent=True) or {}
            cfg = kill_switch.set_config(body)
        else:
            cfg = kill_switch.get_config()
        state = kill_switch.check_and_trip()
        return jsonify({"config": cfg, "state": state})

    @app.route("/api/risk/account-type")
    def api_risk_account_type():
        """Return the IB account type the bot is currently connected to.

        Mobile dashboard reads this on mount to filter trades/positions
        queries by account_type, so paper history never bleeds into live
        stats once the bot is funded.

        Public — no auth — so the mobile app can fetch it before login.
        """
        from lumisignals.account_type import current_account_type
        return jsonify({"account_type": current_account_type()})

    @app.route("/api/strategies/slippage")
    def api_strategies_slippage():
        """Slippage stats per strategy/ticker over a window.

        For each pair (INTENT_OPEN, OPEN) matched by client_intent_id, we
        compute the signed slippage in instrument points:

            BUY:  slippage = fill_price - signal_price  (positive = paid more = adverse)
            SELL: slippage = signal_price - fill_price  (positive = received less = adverse)

        Returns count, average, median, p95, plus a per-direction breakdown
        and the instrument multiplier so the UI can convert points to USD.

        Query params:
            strategy  — strategy_id (default futures_2n20)
            ticker    — instrument (default MES)
            since     — ISO lower bound
            until     — ISO upper bound
            limit     — max events to scan (default 2000)

        Auth: X-Sync-Key.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401

        strategy = request.args.get("strategy") or "futures_2n20"
        ticker = (request.args.get("ticker") or "MES").upper().strip()
        since = request.args.get("since") or None
        until = request.args.get("until") or None
        try:
            limit = int(request.args.get("limit", 2000))
        except ValueError:
            limit = 2000

        from lumisignals.diary import query_events
        rows = query_events(strategy_id=strategy, ticker=ticker,
                            since=since, until=until, limit=limit)

        # Build a {client_intent_id: signal_price} map from INTENT_OPENs.
        intent_signal: dict = {}
        for r in rows:
            if r.get("state") != "INTENT_OPEN":
                continue
            cid = r.get("client_intent_id")
            sp = r.get("signal_price")
            if cid and sp is not None:
                intent_signal[cid] = float(sp)

        # Pair against OPEN fills, parsing direction from reason field.
        pairs: list = []
        for r in rows:
            if r.get("state") != "OPEN":
                continue
            cid = r.get("client_intent_id")
            if not cid or cid not in intent_signal:
                continue
            sp = intent_signal[cid]
            fp = r.get("entry_price")
            if fp is None:
                continue
            reason = (r.get("reason") or "").upper()
            if " BUY" in reason or reason.startswith("BUY") or reason.endswith("BUY"):
                direction = "BUY"
                signed = float(fp) - sp
            elif " SELL" in reason or reason.startswith("SELL") or reason.endswith("SELL"):
                direction = "SELL"
                signed = sp - float(fp)
            else:
                continue
            pairs.append({
                "event_time": r.get("event_time"),
                "direction": direction,
                "signal_price": sp,
                "fill_price": float(fp),
                "slippage_pts": round(signed, 4),
                "client_intent_id": cid,
            })

        # Instrument point multipliers (USD per point per contract).
        MULTIPLIERS = {
            "MES": 5.0, "MNQ": 2.0, "MGC": 10.0, "MCL": 100.0,
            "ES": 50.0, "NQ": 20.0, "GC": 100.0, "CL": 1000.0,
            "RTY": 50.0, "YM": 5.0, "MYM": 0.5, "M2K": 5.0,
        }
        mult = MULTIPLIERS.get(ticker, 1.0)

        def stats(slips: list) -> dict:
            if not slips:
                return {"count": 0, "avg_pts": None, "median_pts": None,
                        "p95_pts": None, "avg_usd": None, "median_usd": None}
            sorted_s = sorted(slips)
            n = len(sorted_s)
            avg = sum(sorted_s) / n
            median = sorted_s[n // 2] if n % 2 == 1 else (sorted_s[n // 2 - 1] + sorted_s[n // 2]) / 2
            p95_idx = max(0, min(n - 1, int(0.95 * n)))
            p95 = sorted_s[p95_idx]
            return {
                "count": n,
                "avg_pts": round(avg, 4),
                "median_pts": round(median, 4),
                "p95_pts": round(p95, 4),
                "avg_usd": round(avg * mult, 2),
                "median_usd": round(median * mult, 2),
            }

        all_slips = [p["slippage_pts"] for p in pairs]
        buy_slips = [p["slippage_pts"] for p in pairs if p["direction"] == "BUY"]
        sell_slips = [p["slippage_pts"] for p in pairs if p["direction"] == "SELL"]

        return jsonify({
            "ticker": ticker,
            "strategy": strategy,
            "multiplier_usd_per_pt": mult,
            "window": {"since": since, "until": until},
            "overall": stats(all_slips),
            "by_direction": {
                "BUY": stats(buy_slips),
                "SELL": stats(sell_slips),
            },
            "recent_pairs": pairs[-25:],  # last 25 for spot-checking
        })

    @app.route("/api/strategies/latency")
    def api_strategies_latency():
        """TV → bot latency stats over a window.

        For each INTENT_OPEN row with tv_latency_seconds populated, computes
        count, average, median, p50, p95, max in seconds.

        Latency = (webhook_received_at − signal_bar_close_at) where
        signal_bar_close_at is the most-recent closed bar in our cache at
        webhook receive time (bar_open + 120s for 2m bars). Captures the
        Pine alert latency + TV delivery latency end-to-end.

        Query params: strategy, ticker, since, until, limit.
        Auth: X-Sync-Key.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401
        strategy = request.args.get("strategy") or "futures_2n20"
        ticker = (request.args.get("ticker") or "MES").upper().strip()
        since = request.args.get("since") or None
        until = request.args.get("until") or None
        try:
            limit = int(request.args.get("limit", 2000))
        except ValueError:
            limit = 2000

        # query_events doesn't currently select tv_latency_seconds; raw fetch.
        url = os.environ.get("SUPABASE_URL") or ""
        key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
        if not url or not key:
            return jsonify({"error": "supabase env missing"}), 500
        import urllib.parse, urllib.request, urllib.error
        params = {
            "select": "event_time,tv_latency_seconds,webhook_received_at,reason",
            "state": "eq.INTENT_OPEN",
            "strategy_id": f"eq.{strategy}",
            "ticker": f"eq.{ticker}",
            "tv_latency_seconds": "not.is.null",
            "order": "event_time.desc",
            "limit": str(max(1, min(limit, 5000))),
        }
        if since and until:
            params["and"] = f"(event_time.gte.{since},event_time.lt.{until})"
        elif since:
            params["event_time"] = f"gte.{since}"
        elif until:
            params["event_time"] = f"lt.{until}"
        q = urllib.parse.urlencode(params)
        req = urllib.request.Request(
            f"{url}/rest/v1/trade_events?{q}",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                rows = json.loads(resp.read())
        except Exception as e:
            return jsonify({"error": f"query failed: {e}"}), 500

        lats = [float(r["tv_latency_seconds"]) for r in rows
                if r.get("tv_latency_seconds") is not None]
        if not lats:
            return jsonify({
                "ticker": ticker, "strategy": strategy,
                "window": {"since": since, "until": until},
                "count": 0, "stats": None,
                "recent": [],
            })
        sorted_l = sorted(lats)
        n = len(sorted_l)
        avg = sum(sorted_l) / n
        median = sorted_l[n // 2] if n % 2 == 1 else (sorted_l[n // 2 - 1] + sorted_l[n // 2]) / 2
        p95_idx = max(0, min(n - 1, int(0.95 * n)))
        return jsonify({
            "ticker": ticker, "strategy": strategy,
            "window": {"since": since, "until": until},
            "count": n,
            "stats": {
                "avg_seconds": round(avg, 3),
                "median_seconds": round(median, 3),
                "p95_seconds": round(sorted_l[p95_idx], 3),
                "max_seconds": round(sorted_l[-1], 3),
                "min_seconds": round(sorted_l[0], 3),
            },
            "recent": [{
                "event_time": r.get("event_time"),
                "webhook_received_at": r.get("webhook_received_at"),
                "tv_latency_seconds": r.get("tv_latency_seconds"),
                "reason": r.get("reason"),
            } for r in rows[:25]],
        })

    @app.route("/api/risk/missed-signal-alert", methods=["GET", "PUT", "POST"])
    def api_risk_missed_signal_alert():
        """Manage + run the missed-signal alert.

        GET  → { config, last_run }   — read current config + last result.
        PUT  → body: any subset of config; returns merged config.
        POST → run check_and_alert() right now (manual trigger). Useful
               for sanity-checking that the alert path works without
               waiting for the 5-min cron.
        Auth: X-Sync-Key header.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401
        from lumisignals import missed_signal_alert
        if request.method == "PUT":
            body = request.get_json(silent=True) or {}
            cfg = missed_signal_alert.set_config(body)
            return jsonify({"config": cfg})
        if request.method == "POST":
            result = missed_signal_alert.check_and_alert()
            return jsonify({"config": missed_signal_alert.get_config(),
                            "result": result})
        return jsonify({"config": missed_signal_alert.get_config()})

    @app.route("/api/risk/reconcile-state", methods=["GET"])
    def api_risk_reconcile_state():
        """Read the restart-safety gate state. Mobile polls this every few
        seconds to show the dashboard banner.

        Public — no auth — so the banner works before login.
        """
        from lumisignals import reconcile_gate
        state = reconcile_gate.get_state()
        return jsonify({"state": state, "locked": reconcile_gate.is_locked()})

    @app.route("/api/risk/reconcile-state/reset", methods=["POST"])
    def api_risk_reconcile_state_reset():
        """Manual unlock from a timed_out state. The user is taking
        responsibility for broker/bot state being consistent.

        Auth: X-Sync-Key header.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401
        from lumisignals import reconcile_gate
        state = reconcile_gate.manual_reset()
        return jsonify({"state": state})

    @app.route("/api/risk/flatten-all", methods=["POST"])
    def api_risk_flatten_all():
        """Emergency: queue a MKT close for every currently-open futures
        position. Returns the list of orders queued so the caller can
        verify each leg.

        Designed for the "bot is misbehaving and I need to be flat
        NOW" workflow: user opens mobile Settings → Flatten All, taps,
        confirms. Each open futures contract gets a MKT close queued
        to ibkr:order:pending — same path as a normal TV close webhook.

        Bypasses the futures BUY/SELL gate stack since closes are
        always safer than holding. Still goes through ibkr-sync, which
        validates against IB state and uses the atomic STP→MKT modify
        when possible to avoid double-stop fills.

        Auth: X-Sync-Key header.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401
        import redis as _redis
        import uuid
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

        # Read current IB positions from the sync's cached snapshot.
        raw = rdb.get("ibkr:data:1")
        if not raw:
            return jsonify({
                "status": "error",
                "reason": "no_ibkr_data_in_cache",
                "detail": "ibkr-sync has not pushed positions yet — try again in a few seconds",
            }), 503
        try:
            data = json.loads(raw)
            positions = data.get("positions", []) or []
        except Exception as e:
            return jsonify({"status": "error", "reason": str(e)}), 500

        queued = []
        skipped = []
        for p in positions:
            qty = int(p.get("position", 0))
            if qty == 0:
                continue
            sym = (p.get("symbol") or p.get("contractDesc") or "").upper()
            if not sym:
                skipped.append({"reason": "no_symbol", "position": p})
                continue
            # Direction = opposite of current net. Long N → SELL N; Short N → BUY N.
            close_dir = "CLOSE_LONG" if qty > 0 else "CLOSE_SHORT"
            order_id = str(uuid.uuid4())[:8]
            order = {
                "order_id": order_id,
                "queued_at": datetime.now(timezone.utc).isoformat(),
                "user_id": 1,
                "ticker": sym,
                "type": "futures",
                "direction": close_dir,
                "strategy": "emergency_flatten",
                "reason": "Emergency Flatten All",
                "contracts": abs(qty),
                "status": "queued",
            }
            rdb.setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))
            queued.append({"ticker": sym, "qty": qty, "direction": close_dir,
                          "order_id": order_id})

        logger.warning("FLATTEN ALL: queued %d close order(s), skipped %d",
                       len(queued), len(skipped))
        return jsonify({
            "status": "queued",
            "queued": queued,
            "skipped": skipped,
            "count": len(queued),
        })

    @app.route("/api/risk/cooldown", methods=["GET", "PUT"])
    def api_risk_cooldown():
        """Read or update the per-(strategy, ticker) cooldown config.

        GET  → { config }
        PUT  → body: { enabled?, cooldown_secs? }
        Auth: X-Sync-Key.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401
        from lumisignals import cooldown
        if request.method == "PUT":
            body = request.get_json(silent=True) or {}
            cfg = cooldown.set_config(body)
        else:
            cfg = cooldown.get_config()
        return jsonify({"config": cfg})

    @app.route("/api/risk/cooldown/clear", methods=["POST"])
    def api_risk_cooldown_clear():
        """Manually clear an active cooldown. Body: { strategy, ticker }."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401
        from lumisignals import cooldown
        body = request.get_json(silent=True) or {}
        strategy = body.get("strategy", "")
        ticker = body.get("ticker", "")
        if not strategy or not ticker:
            return jsonify({"error": "strategy and ticker required"}), 400
        cleared = cooldown.clear(strategy, ticker)
        return jsonify({"cleared": cleared, "strategy": strategy, "ticker": ticker})

    @app.route("/api/risk/runaway-guard", methods=["GET", "PUT"])
    def api_risk_runaway_guard():
        """Read or update the runaway guard (max-trades-per-day +
        consecutive-loss circuit breaker).

        Query param `strategy` selects per-strategy state/config.
        Omit it for the legacy global keys.

        GET  → { config, state }
        PUT  → body: any subset of { enabled, max_trades_per_day,
                                      max_consecutive_losses,
                                      reset_hour_et, reset_minute_et }
        Auth: X-Sync-Key.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401
        from lumisignals import runaway_guard
        strategy = request.args.get("strategy") or None
        if request.method == "PUT":
            body = request.get_json(silent=True) or {}
            cfg = runaway_guard.set_config(body, strategy=strategy)
        else:
            cfg = runaway_guard.get_config(strategy)
        return jsonify({"config": cfg, "state": runaway_guard.get_state(strategy),
                        "strategy": strategy})

    @app.route("/api/risk/runaway-guard/reset", methods=["POST"])
    def api_risk_runaway_guard_reset():
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401
        from lumisignals import runaway_guard
        strategy = request.args.get("strategy") or None
        state = runaway_guard.manual_reset(strategy)
        return jsonify({"state": state, "strategy": strategy})

    @app.route("/api/strategies/mtf-config", methods=["GET", "PUT"])
    def api_strategies_mtf_config():
        """Read or update the MTF / swing-setup tuning parameters used by
        swing_setup.compute_setup (shares stop ×ATR, entry proximity ×ATR,
        per-mode target R:R floors).

        GET → { config }
        PUT → body: any subset of { stop_atr_mult, proximity_atr_mult,
                                    rr_floor_scalp, rr_floor_intraday,
                                    rr_floor_swing }
        Auth: X-Sync-Key header.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401
        from lumisignals import mtf_config
        if request.method == "PUT":
            body = request.get_json(silent=True) or {}
            cfg = mtf_config.set_config(body)
        else:
            cfg = mtf_config.get_config()
        return jsonify({"config": cfg, "defaults": mtf_config.DEFAULT_CONFIG})

    @app.route("/api/risk/position-guard", methods=["GET", "PUT"])
    def api_risk_position_guard():
        """Read or update the position size guard.

        GET  → { config, positions: {ticker: current_net} }
        PUT  → body: any subset of { enabled, default_limit, limits }
                where `limits` is {ticker: int} per-ticker overrides.
                returns the new merged config.
        Auth: X-Sync-Key header.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401
        from lumisignals import position_guard
        if request.method == "PUT":
            body = request.get_json(silent=True) or {}
            cfg = position_guard.set_config(body)
        else:
            cfg = position_guard.get_config()
        # Surface current net for known futures so the UI can show
        # "MES: +1, MNQ: 0" alongside the limits.
        positions: dict = {}
        for t in ("MES", "MNQ", "MGC", "MCL", "ES", "NQ", "GC", "CL"):
            n = position_guard.current_net_contracts(t)
            if n != 0:
                positions[t] = n
        return jsonify({"config": cfg, "positions": positions})

    @app.route("/api/risk/kill-switch/reset", methods=["POST"])
    def api_risk_kill_switch_reset():
        """Manually clear a tripped state. Day P&L stays as is."""
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401
        from lumisignals import kill_switch
        state = kill_switch.manual_reset()
        return jsonify({"state": state})

    @app.route("/api/strategies/expected-signals")
    def api_strategies_expected_signals():
        """Replay 2n20 entry+exit logic on cached bars to surface what Pine
        should have fired — useful for finding signals we never received as
        webhooks (TV delivery loss, alert quota, etc.).

        Query params:
            ticker    — e.g. MES (required for now; only MES bars cached)
            since     — ISO timestamp lower bound (clip the replay window)
            until     — ISO timestamp upper bound
            mode      — "expected" (default): list every signal the replay fires
                        "missed":   only signals with no matching INTENT_OPEN
                                    in trade_events (within 90s of bar close)
                        "diff":     full {missed, matched, extras} breakdown

        Auth: X-Sync-Key header.
        """
        sync_key = request.headers.get("X-Sync-Key", "")
        if sync_key != os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026"):
            return jsonify({"error": "unauthorized"}), 401

        ticker = (request.args.get("ticker") or "MES").upper().strip()
        since = request.args.get("since") or None
        until = request.args.get("until") or None
        mode = (request.args.get("mode") or "expected").lower()

        # Currently only MES bars are cached in Redis. Future strategies/
        # tickers would pull from Polygon/Massive instead.
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = rdb.get(f"ibkr:bars:{ticker}:2m")
        if not raw:
            return jsonify({"error": f"no cached bars for {ticker}"}), 404
        cached = json.loads(raw)
        bars = cached.get("bars", [])

        # Clip the bar window to [since, until] BEFORE the replay so VWAP
        # anchoring still has the prior session context. Actually — VWAP
        # anchors daily at 18:00 ET, so we need bars back to that anchor
        # for accurate replay. Simpler: replay over the full cached window
        # then filter the output by [since, until].
        from lumisignals.strategy_replay import replay_2n20_signals, diff_against_diary
        all_signals = replay_2n20_signals(bars)

        def in_window(iso: str) -> bool:
            if since and iso < since:
                return False
            if until and iso >= until:
                return False
            return True
        signals = [s for s in all_signals if in_window(s["bar_time"])]

        if mode == "expected":
            return jsonify({"ticker": ticker, "count": len(signals),
                            "signals": signals})

        # missed/diff modes: also pull actual diary INTENT_OPEN events for
        # the same window so we can diff.
        from lumisignals.diary import query_events
        # Slightly widen the since/until for the diary query so we capture
        # INTENT_OPENs whose bar-close timestamps sit near the edge.
        actual = query_events(strategy_id="futures_2n20", ticker=ticker,
                              since=since, until=until, limit=5000)
        actual_entries = [a for a in actual if a.get("state") == "INTENT_OPEN"]
        diff = diff_against_diary(signals, actual_entries)
        if mode == "missed":
            return jsonify({"ticker": ticker, "count": len(diff["missed"]),
                            "missed": diff["missed"]})
        return jsonify({"ticker": ticker, **{k: len(v) for k, v in diff.items()},
                        "details": diff})

    @app.route("/api/adx/direction")
    def api_adx_direction():
        """ADX direction per TF for a single instrument.

        Used by the mobile chart header to render trend arrows next to
        the ticker (same look as the positions/watchlist rows).

        Query params:
          pair: e.g. EUR_USD or EURUSD (forex), MES (futures), SPY (stock)
          tfs:  comma-separated TFs to compute. Default "5m,15m,1h".

        Returns {tfs: {tf: "UP"|"DOWN"|"SIDE"}, pair, ts}.
        """
        pair_raw = (request.args.get("pair") or "").upper().strip()
        if not pair_raw:
            return jsonify({"error": "missing ?pair"}), 400
        tfs_raw = request.args.get("tfs") or "5m,15m,1h"
        tfs = [t.strip() for t in tfs_raw.split(",") if t.strip()]
        if not tfs:
            return jsonify({"error": "no tfs"}), 400

        # Forex pairs may arrive as USD_CAD or USDCAD; normalize.
        if "_" in pair_raw:
            pair = pair_raw
        elif len(pair_raw) == 6 and pair_raw.isalpha():
            pair = pair_raw[:3] + "_" + pair_raw[3:]
        else:
            pair = pair_raw

        is_forex = ("_" in pair) or (len(pair_raw) == 6 and pair_raw.isalpha())
        out = {tf: "SIDE" for tf in tfs}
        if not is_forex:
            return jsonify({"pair": pair, "tfs": out, "source": "neutral"})

        # Pull bars from the SAME source the chart uses (Polygon via
        # MassiveClient). Previously this endpoint hit Oanda directly with
        # count=250 + complete-only filtering, which excluded the
        # in-progress monthly candle and produced different pivots than
        # the chart's dashboard. Result: title arrow said UP, dashboard
        # said DOWN for the same instrument and TF. Aligning the data
        # source guarantees they agree.
        massive_key = os.environ.get("MASSIVE_API_KEY", "")
        if not massive_key:
            return jsonify({"pair": pair, "tfs": out, "error": "no polygon key"}), 200

        from lumisignals.massive_client import get_shared_client
        from lumisignals.untouched_levels import calculate_trend_direction
        massive = get_shared_client(massive_key)
        poly_ticker = f"C:{pair.replace('_', '')}"

        class _C:
            __slots__ = ("high", "low", "close")
            def __init__(self, h, l, c):
                self.high, self.low, self.close = h, l, c

        for tf in tfs:
            try:
                # 300 bars: same default as the chart's /api/candles call
                # for monthly (the largest TF). For lower TFs this is just
                # extra context for the pivot detector.
                cs = massive.get_candles(poly_ticker, tf, 300)
                bars = []
                for c in cs:
                    try:
                        bars.append(_C(float(c.high), float(c.low), float(c.close)))
                    except Exception:
                        continue
                if len(bars) < 32:
                    continue
                # prefer_confirmed=True so a marginal close above the last
                # swing high doesn't flip a visually-LH+LL structure to UP.
                # The chart's JS dashboard doesn't do that override, and we
                # want the title arrow to match what the user sees.
                direction, _val = calculate_trend_direction(
                    bars, instrument=pair, prefer_confirmed=True)
                out[tf] = direction
            except Exception:
                continue

        return jsonify({"pair": pair, "tfs": out, "source": "polygon"})

    @app.route("/api/h1_zone/state")
    def api_h1_zone_state():
        """Live state for the H1 Zone Scalp strategy on one pair.

        Returns:
            {
              pair, current_price,
              zones: {d1, d2, s1, s2},
              trend: {m15: "UP|DOWN|SIDE", h1: "..."},
              bundles: [
                {variant, direction, entry, stop,
                 targets: {T1, T2, T3, T4}, legs_state: {T1: "pending"|"filled"|"closed", ...}}
              ],
              fills: [{time, label, variant, direction, price, pl, reason}]
            }
        """
        pair = (request.args.get("pair") or "").upper().strip()
        if not pair:
            return jsonify({"error": "Missing ?pair"}), 400

        # Get active user's Oanda creds (same pattern as bot_runner)
        import psycopg2
        try:
            with psycopg2.connect(os.environ.get(
                "DATABASE_URL",
                "postgresql://lumisignals:LumiBot2026@localhost/lumisignals_db"
            )) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT oanda_api_key, oanda_account_id, oanda_environment "
                    "FROM users WHERE bot_active=true AND oanda_api_key IS NOT NULL "
                    "ORDER BY id LIMIT 1")
                row = cur.fetchone()
            if not row:
                return jsonify({"error": "no active oanda user"}), 503
            key, acct, env = row
        except Exception as e:
            return jsonify({"error": f"db: {e}"}), 500

        from lumisignals.oanda_client import OandaClient
        from lumisignals.untouched_levels import (
            find_untouched_levels, calculate_trend_direction,
        )
        oa = OandaClient(account_id=acct, api_key=key, environment=env or "practice")

        def _parse_candles(resp):
            out = []
            for c in resp.get("candles", []):
                if not c.get("complete"):
                    continue
                mid = c.get("mid") or {}
                try:
                    out.append({
                        "time": c.get("time"),
                        "open": float(mid["o"]),
                        "high": float(mid["h"]),
                        "low":  float(mid["l"]),
                        "close": float(mid["c"]),
                    })
                except Exception:
                    continue
            return out

        # ── Candles + zones + trend ──
        # Trend on 15m/1h uses N=15 structure for FX. Need enough history
        # for multiple confirmed pivot pairs (small counts find micro
        # pivots only and misread the macro regime). 250 bars covers it.
        try:
            h1 = _parse_candles(oa._request(
                "GET", f"/v3/instruments/{pair}/candles?granularity=H1&count=30&price=M"))
            m5 = _parse_candles(oa._request(
                "GET", f"/v3/instruments/{pair}/candles?granularity=M5&count=2&price=M"))
            m15 = _parse_candles(oa._request(
                "GET", f"/v3/instruments/{pair}/candles?granularity=M15&count=250&price=M"))
            h1_for_trend = _parse_candles(oa._request(
                "GET", f"/v3/instruments/{pair}/candles?granularity=H1&count=250&price=M"))
        except Exception as e:
            return jsonify({"error": f"oanda candles: {e}"}), 502

        current_price = m5[-1]["close"] if m5 else (h1[-1]["close"] if h1 else 0.0)
        if h1:
            highs = [b["high"] for b in reversed(h1)]
            lows  = [b["low"]  for b in reversed(h1)]
            s1, s2, d1, d2 = find_untouched_levels(highs, lows, current_price, lookback=10)
        else:
            s1 = s2 = d1 = d2 = None

        class _C:
            __slots__ = ("high", "low", "close")
            def __init__(self, h, l, c):
                self.high, self.low, self.close = h, l, c

        m15_dir, _ = (calculate_trend_direction(
            [_C(b["high"], b["low"], b["close"]) for b in m15], instrument=pair)
            if len(m15) >= 32 else ("SIDE", 0.0))
        h1_dir, _ = (calculate_trend_direction(
            [_C(b["high"], b["low"], b["close"]) for b in h1_for_trend], instrument=pair)
            if len(h1_for_trend) >= 32 else ("SIDE", 0.0))

        # ── Active bundles: pending + open trades tagged for this pair ──
        bundles_by_variant: dict = {}  # variant -> dict
        try:
            pend = oa._request("GET", f"/v3/accounts/{acct}/pendingOrders")
            open_t = oa._request("GET", f"/v3/accounts/{acct}/openTrades")
        except Exception as e:
            pend = {"orders": []}
            open_t = {"trades": []}

        def _ingest_leg(variant, direction, label, entry, stop, target, state):
            b = bundles_by_variant.setdefault(variant, {
                "variant": variant,
                "direction": direction,
                "entry": entry,
                "stop": stop,
                "targets": {},
                "legs_state": {},
            })
            b["targets"][label] = target
            b["legs_state"][label] = state

        for o in pend.get("orders", []):
            if o.get("instrument") != pair:
                continue
            tag = ((o.get("clientExtensions") or {}).get("tag") or "")
            if not tag.startswith("scalp_h1zone:"):
                continue
            parts = tag.split(":")
            if len(parts) != 4:
                continue
            _, variant, _pair2, label = parts
            try:
                units = int(float(o.get("units", 0)))
            except Exception:
                continue
            direction = "BUY" if units > 0 else "SELL"
            entry = float(o.get("price", 0))
            stop = float(((o.get("stopLossOnFill") or {}).get("price") or 0))
            target = float(((o.get("takeProfitOnFill") or {}).get("price") or 0))
            _ingest_leg(variant, direction, label, entry, stop, target, "pending")

        for t in open_t.get("trades", []):
            if t.get("instrument") != pair:
                continue
            tag = ((t.get("clientExtensions") or {}).get("tag") or "")
            if not tag.startswith("scalp_h1zone:"):
                continue
            parts = tag.split(":")
            if len(parts) != 4:
                continue
            _, variant, _pair2, label = parts
            try:
                units = int(float(t.get("currentUnits", 0)))
            except Exception:
                continue
            direction = "BUY" if units > 0 else "SELL"
            entry = float(t.get("price", 0))
            stop = float(((t.get("stopLossOrder") or {}).get("price") or 0))
            target = float(((t.get("takeProfitOrder") or {}).get("price") or 0))
            _ingest_leg(variant, direction, label, entry, stop, target, "filled")

        # ── Recent fills/closes (last 24h) ──
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        since = (_dt.now(_tz.utc) - _td(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        until = (_dt.now(_tz.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fills = []
        try:
            idx = oa._request(
                "GET",
                f"/v3/accounts/{acct}/transactions?from={since}&to={until}&type=ORDER_FILL")
            pages = idx.get("pages", [])
            txs = []
            for url in pages:
                endpoint = "/v3/" + url.split("/v3/")[1]
                page = oa._request("GET", endpoint)
                txs.extend(page.get("transactions", []))
        except Exception:
            txs = []

        for tx in txs:
            if tx.get("instrument") != pair:
                continue
            order_id = tx.get("orderID")
            # Trace tag back via the originating order's clientExtensions.
            # Oanda includes orderExtensions or orderFilledExtensions on the
            # ORDER_FILL transaction when the matched order had any.
            tag = (((tx.get("orderFilledClientExtensions") or {})
                    .get("tag")) or
                   ((tx.get("clientExtensions") or {}).get("tag")) or
                   "")
            if not tag.startswith("scalp_h1zone:"):
                continue
            parts = tag.split(":")
            if len(parts) != 4:
                continue
            _, variant, _pair2, label = parts
            try:
                units = int(float(tx.get("units", 0)))
            except Exception:
                units = 0
            direction = "BUY" if units > 0 else "SELL"
            price = float(tx.get("price", 0))
            reason = tx.get("reason", "")
            pl = float(tx.get("pl", 0))
            fills.append({
                "time": tx.get("time", ""),
                "label": label,
                "variant": variant,
                "direction": direction,
                "price": price,
                "pl": pl,
                "reason": reason,
            })

        return jsonify({
            "pair": pair,
            "current_price": current_price,
            "zones": {"s1": s1, "s2": s2, "d1": d1, "d2": d2},
            "trend": {"m15": m15_dir, "h1": h1_dir},
            "bundles": list(bundles_by_variant.values()),
            "fills": fills,
        })

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
        # 7-day TTL so last-known levels survive weekends + holiday closes
        # (markets can be dark ~65-90h). The compare page's staleness badge
        # flags them as not-live; a fresh push overwrites this anyway.
        rdb.setex(f"tv:levels:{ticker}", 604800, json.dumps(store))
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
        interval_to_tf = {"3mo": "Q", "1mo": "M", "1w": "W", "1d": "D",
                          "4h": "4H", "1h": "1H", "30m": "30M", "15m": "15M"}
        snr_intervals = ["3mo", "1mo", "1w", "1d", "4h", "1h", "30m", "15m"]
        # Trade-builder for trend data. LumiTrade exposes 30m/15m trends
        # only under the spelled-out keys "thirtyminute"/"fifteenminute"
        # ("30m"/"15m"/"30min" all return null). Mapped by label to the
        # 30M/15M rows for consistency with the existing offset convention
        # (LT's frequency names run one step coarser than the literal bar
        # interval — e.g. LT "hourly" is computed on 4h bars).
        freq_to_tf = {"quarterly": "Q", "monthly": "M", "weekly": "W", "daily": "D",
                      "fourhour": "4H", "hourly": "1H",
                      "thirtyminute": "30M", "fifteenminute": "15M"}
        frequencies = ["quarterly", "monthly", "weekly", "daily", "fourhour", "hourly",
                       "thirtyminute", "fifteenminute"]

        # Built-in Polygon levels (replaces LumiTrade API)
        massive_key = os.environ.get("MASSIVE_API_KEY", "")
        massive = None
        if massive_key:
            from lumisignals.massive_client import get_shared_client
            from lumisignals.untouched_levels import (
                find_htf_levels, HTF_TF_LOOKBACK, calculate_adx_direction)
            massive = get_shared_client(massive_key)

        # Cash indexes need Polygon's "I:" prefix or they return 0 bars
        INDEX_SYMBOLS = {"SPX", "NDX", "RUT", "VIX", "DJI", "XSP", "XND"}
        # Crypto bases (BTC, ETH, ...) — same 6-char shape as forex but must
        # route to Polygon "X:" not OANDA. Derived from the canonical list.
        from lumisignals.massive_client import CRYPTO_TICKERS
        CRYPTO_BASES = {t[2:] for t in CRYPTO_TICKERS}  # "X:BTCUSD" -> "BTCUSD"

        results = []
        for ticker in tickers:
            item = {"ticker": ticker, "server": {}, "tradingview": {}, "tv_trends": {}, "server_trends": {}, "tv_updated": ""}

            # Determine if ticker is forex (e.g. EURUSD, GBPUSD)
            is_crypto = ticker in CRYPTO_BASES
            is_forex = (len(ticker) == 6 and ticker[:3].isalpha() and ticker[3:].isalpha()
                        and ticker not in ("GOOGL",) and not is_crypto)
            # Data source per asset class: forex → OANDA (matches TV-OANDA
            # + the bot's trades); crypto + everything else → Polygon.
            item["feed"] = "OANDA" if is_forex else "Polygon"

            if is_forex:
                oc = _get_oanda_md_client()
                if oc is not None:
                    srv, trd, cp = _oanda_forex_levels(oc, ticker)
                    item["server"] = srv
                    item["server_trends"] = trd
                    if cp is not None:
                        item["current_price"] = cp
                else:
                    item["server"]["error"] = "OANDA creds not configured"
                # Second comparison: Polygon-aligned forex (5pm-ET windows)
                # — pairs with the LT (LumiTrade Polygon) column so you can
                # validate LumiTrade's Polygon forex against ours.
                if massive:
                    psrv, ptrd, _pcp = _polygon_levels(massive, f"C:{ticker}")
                    item["server_polygon"] = psrv
                    item["server_polygon_trends"] = ptrd
            elif massive:
                if is_crypto:
                    poly_ticker = f"X:{ticker}"   # crypto → Polygon X: feed (24/7, UTC-day bars)
                elif ticker in INDEX_SYMBOLS:
                    poly_ticker = f"I:{ticker}"
                else:
                    poly_ticker = ticker

                for tf, tf_label in interval_to_tf.items():
                    try:
                        # Deep per-TF lookback so the SRV levels match what
                        # the Pine script draws (the TV column). Fetch a few
                        # extra bars beyond the lookback for the current bar.
                        lb = HTF_TF_LOOKBACK.get(tf, 50)
                        count = lb + 5
                        candles = massive.get_candles(poly_ticker, tf, count)
                        if not candles or len(candles) < 3:
                            continue
                        price = candles[-1].close
                        highs = [c.high for c in reversed(candles)]
                        lows = [c.low for c in reversed(candles)]
                        s1, s2, d1, d2 = find_htf_levels(highs, lows, price, lookback=lb)
                        item["server"][tf_label] = {
                            "supply": s1, "supply2": s2,
                            "demand": d1, "demand2": d2,
                        }
                        # ADX trend
                        direction, _adx = calculate_adx_direction(candles)
                        item["server_trends"][tf_label] = direction
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
                                "type": "forex" if is_forex else ("indices" if ticker in INDEX_SYMBOLS else "stock"), "days": 256},
                        timeout=15,
                    )
                    if resp.status_code == 200:
                        snr_data = resp.json().get("data", resp.json())
                        for interval, tf_label in interval_to_tf.items():
                            tf_data = snr_data.get(interval, {})
                            if isinstance(tf_data, dict):
                                # The API returns two levels each:
                                # resistance_price1/2 (supply) and
                                # support_price1/2 (demand). Fall back to the
                                # singular convenience field for S1/D1 when the
                                # numbered one is absent.
                                item["lumitrade"][tf_label] = {
                                    "supply": tf_data.get("resistance_price1", tf_data.get("resistance_price")),
                                    "supply2": tf_data.get("resistance_price2"),
                                    "demand": tf_data.get("support_price1", tf_data.get("support_price")),
                                    "demand2": tf_data.get("support_price2"),
                                }
                except Exception as e:
                    item["lumitrade"]["error"] = str(e)

                try:
                    resp2 = session.get(
                        f"{snr_base_url}/partners/technical-analysis/trade-builder-setup",
                        params={"ticker": ticker, "period": 14,
                                "market": "forex" if is_forex else ("indices" if ticker in INDEX_SYMBOLS else "stock"),
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

    @app.route("/api/mobile/compare/levels")
    def api_mobile_compare_levels():
        """Mobile-friendly version of /api/compare/levels — no login required.
        Uses the env LUMITRADE_API_KEY directly. Same return shape so the
        mobile WebView can use a shared rendering template."""
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

        tickers = request.args.get("tickers", "SPY,QQQ,NVDA,SPX,NDX,XSP,RUT,EURUSD,GBPUSD,USDJPY").upper().split(",")
        tickers = [t.strip() for t in tickers if t.strip()]

        snr_base_url = "https://app.lumitrade.ai/api/v1"
        snr_api_key = os.environ.get("LUMITRADE_API_KEY", "")

        interval_to_tf = {"3mo": "Q", "1mo": "M", "1w": "W", "1d": "D",
                          "4h": "4H", "1h": "1H", "30m": "30M", "15m": "15M"}
        snr_intervals = ["3mo", "1mo", "1w", "1d", "4h", "1h", "30m", "15m"]
        # 30m/15m trends only under "thirtyminute"/"fifteenminute" keys.
        freq_to_tf = {"quarterly": "Q", "monthly": "M", "weekly": "W", "daily": "D",
                      "fourhour": "4H", "hourly": "1H",
                      "thirtyminute": "30M", "fifteenminute": "15M"}
        frequencies = ["quarterly", "monthly", "weekly", "daily", "fourhour", "hourly",
                       "thirtyminute", "fifteenminute"]

        massive_key = os.environ.get("MASSIVE_API_KEY", "")
        massive = None
        if massive_key:
            from lumisignals.massive_client import get_shared_client
            from lumisignals.untouched_levels import (
                find_htf_levels, HTF_TF_LOOKBACK, calculate_adx_direction)
            massive = get_shared_client(massive_key)

        # Cash indexes need Polygon's "I:" prefix or they return 0 bars
        INDEX_SYMBOLS = {"SPX", "NDX", "RUT", "VIX", "DJI", "XSP", "XND"}
        # Crypto bases (BTC, ETH, ...) — same 6-char shape as forex but must
        # route to Polygon "X:" not OANDA. Derived from the canonical list.
        from lumisignals.massive_client import CRYPTO_TICKERS
        CRYPTO_BASES = {t[2:] for t in CRYPTO_TICKERS}  # "X:BTCUSD" -> "BTCUSD"

        results = []
        for ticker in tickers:
            item = {"ticker": ticker, "server": {}, "tradingview": {}, "tv_trends": {}, "server_trends": {}, "tv_updated": ""}
            is_crypto = ticker in CRYPTO_BASES
            is_forex = (len(ticker) == 6 and ticker[:3].isalpha() and ticker[3:].isalpha()
                        and ticker not in ("GOOGL",) and not is_crypto)
            # Forex → OANDA (matches TV-OANDA + the bot's trades); crypto +
            # everything else → Polygon.
            item["feed"] = "OANDA" if is_forex else "Polygon"

            if is_forex:
                oc = _get_oanda_md_client()
                if oc is not None:
                    srv, trd, cp = _oanda_forex_levels(oc, ticker)
                    item["server"] = srv
                    item["server_trends"] = trd
                    if cp is not None:
                        item["current_price"] = cp
                else:
                    item["server"]["error"] = "OANDA creds not configured"
                # Second comparison: Polygon-aligned forex (5pm-ET windows)
                # — pairs with the LT (LumiTrade Polygon) column so you can
                # validate LumiTrade's Polygon forex against ours.
                if massive:
                    psrv, ptrd, _pcp = _polygon_levels(massive, f"C:{ticker}")
                    item["server_polygon"] = psrv
                    item["server_polygon_trends"] = ptrd
            elif massive:
                if is_crypto:
                    poly_ticker = f"X:{ticker}"   # crypto → Polygon X: feed (24/7, UTC-day bars)
                elif ticker in INDEX_SYMBOLS:
                    poly_ticker = f"I:{ticker}"
                else:
                    poly_ticker = ticker
                for tf, tf_label in interval_to_tf.items():
                    try:
                        # Deep per-TF lookback so SRV matches the Pine/TV
                        # levels (find_htf_levels is the port of the Pine
                        # algorithm). Fetch a few extra bars for the current.
                        lb = HTF_TF_LOOKBACK.get(tf, 50)
                        count = lb + 5
                        candles = massive.get_candles(poly_ticker, tf, count)
                        if not candles or len(candles) < 3:
                            continue
                        price = candles[-1].close
                        # Track the freshest last-close across all TFs.
                        # Lowest TF wins (most current).
                        if (item.get("current_price") is None
                            or tf in ("15m", "30m", "1h")):
                            item["current_price"] = price
                        highs = [c.high for c in reversed(candles)]
                        lows = [c.low for c in reversed(candles)]
                        s1, s2, d1, d2 = find_htf_levels(highs, lows, price, lookback=lb)
                        # Range high/low for the position-bar visualization
                        # on the Dashboard panel. Same lookback window as
                        # the zones — 12 bars back from most-recent.
                        recent_highs = [c.high for c in candles[-12:]]
                        recent_lows = [c.low for c in candles[-12:]]
                        item["server"][tf_label] = {
                            "supply": s1, "supply2": s2,
                            "demand": d1, "demand2": d2,
                            "range_high": max(recent_highs) if recent_highs else None,
                            "range_low": min(recent_lows) if recent_lows else None,
                        }
                        direction, adx_val = calculate_adx_direction(candles, period=14)
                        item["server_trends"][tf_label] = direction
                    except Exception as e:
                        logger.debug("Mobile compare level err %s %s: %s", ticker, tf, e)
            else:
                item["server"]["error"] = "No Polygon API key configured"

            tv_raw = rdb.get(f"tv:levels:{ticker}")
            if tv_raw:
                tv_data = json.loads(tv_raw)
                item["tradingview"] = tv_data.get("levels", {})
                item["tv_trends"] = tv_data.get("trends", {})
                item["tv_updated"] = tv_data.get("updated_at", "")

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
                                "type": "forex" if is_forex else ("indices" if ticker in INDEX_SYMBOLS else "stock"), "days": 256},
                        timeout=15,
                    )
                    if resp.status_code == 200:
                        snr_data = resp.json().get("data", resp.json())
                        for interval, tf_label in interval_to_tf.items():
                            tf_data = snr_data.get(interval, {})
                            if isinstance(tf_data, dict):
                                # The API returns two levels each:
                                # resistance_price1/2 (supply) and
                                # support_price1/2 (demand). Fall back to the
                                # singular convenience field for S1/D1 when the
                                # numbered one is absent.
                                item["lumitrade"][tf_label] = {
                                    "supply": tf_data.get("resistance_price1", tf_data.get("resistance_price")),
                                    "supply2": tf_data.get("resistance_price2"),
                                    "demand": tf_data.get("support_price1", tf_data.get("support_price")),
                                    "demand2": tf_data.get("support_price2"),
                                }
                except Exception as e:
                    item["lumitrade"]["error"] = str(e)

                try:
                    resp2 = session.get(
                        f"{snr_base_url}/partners/technical-analysis/trade-builder-setup",
                        params={"ticker": ticker, "period": 14,
                                "market": "forex" if is_forex else ("indices" if ticker in INDEX_SYMBOLS else "stock"),
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
                                    dir_str = ("UP" if pos in ("positive", "long")
                                               else "DOWN" if pos in ("negative", "short")
                                               else "SIDE")
                                    item["lt_trends"][tv_tf] = dir_str
                except Exception:
                    pass

            results.append(item)

        return jsonify({"tickers": results})

    @app.route("/mobile_compare")
    def mobile_compare_page():
        """Mobile WebView-friendly compare page. No login. Strips the
        full-site navigation; everything else renders identically."""
        return render_template("mobile_compare.html")

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

        from lumisignals.massive_client import get_shared_client, CORE_TICKERS, SWING_TICKERS, TICKER_NAMES
        from lumisignals.untouched_levels import scan_universe, scan_ticker, TIMEFRAMES

        client = get_shared_client(massive_key)
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

        from lumisignals.massive_client import get_shared_client
        from lumisignals.untouched_levels import scan_ticker

        client = get_shared_client(massive_key)
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

        from lumisignals.massive_client import get_shared_client
        from lumisignals.swing_scanner import run_swing_scan

        client = get_shared_client(massive_key)
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
        # Canonicalize the strategy slug at the webhook boundary. Pine
        # sends raw labels like "2n20" / "fx_2n20" / "tidewater_swing";
        # the rest of the bot stores state and writes diary rows under
        # the mapped slug (futures_2n20 / fx_4h_trend / etc.). Mapping
        # here ensures strat_pos, the runaway_guard counter, the bracket
        # coid, and the reconciler all agree on a single key — without
        # this, the fills watcher used the raw slug while the
        # reconciler decoded the mapped slug from the coid, producing
        # two strat_pos rows per fill and duplicate Closed Trades rows.
        raw_strategy = data.get("strategy", "tradingview")
        from lumisignals import diary as _diary
        strategy = _diary.strategy_slug(raw_strategy) or raw_strategy

        # Normalize Pine's exit-alert direction names. TradingView's 2n20
        # script emits X-LONG / X-SHORT / VWAP-X-L / VWAP-X-S on exits;
        # the webhook contract is BUY / SELL / CLOSE_LONG / CLOSE_SHORT.
        # Without this, every exit signal was returning HTTP 400 and the
        # bot saw entries but no closes — half the day's alerts vanishing.
        # The original Pine label is preserved as `reason` so the closed-
        # trade row carries "VWAP Cross" / "Green Takeout Red" etc.
        _PINE_DIR_MAP = {
            "X-LONG":     "CLOSE_LONG",
            "X-SHORT":    "CLOSE_SHORT",
            "VWAP-X-L":   "CLOSE_LONG",
            "VWAP-X-S":   "CLOSE_SHORT",
            "LONG":       "BUY",          # some Pine alerts use LONG/SHORT
            "SHORT":      "SELL",
        }
        if direction in _PINE_DIR_MAP:
            if not data.get("reason"):
                data["reason"] = direction  # preserve original label
            direction = _PINE_DIR_MAP[direction]

        # TV → bot latency (Tier 2 #9): capture webhook arrival time and
        # the most-recent closed bar at that moment so we can compute
        # latency = (received_at − bar_close_at). Bar close = bar_open
        # + 120s for 2m bars. Stored on the queued order; threaded into
        # the diary's INTENT_OPEN row by ibkr-sync.
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        webhook_received_at = _dt.now(_tz.utc)
        tv_latency_seconds = None
        if direction in ("BUY", "SELL") and ticker:
            try:
                import redis as _r
                rdb = _r.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
                raw = rdb.get(f"ibkr:bars:{ticker}:2m")
                if raw:
                    cached = json.loads(raw)
                    bars = cached.get("bars", []) or []
                    if bars:
                        last_bar = bars[-1]
                        t = last_bar.get("time", 0)
                        if isinstance(t, (int, float)):
                            bar_open = _dt.fromtimestamp(int(t), tz=_tz.utc)
                        else:
                            bar_open = _dt.fromisoformat(str(t).replace("Z", "+00:00"))
                        bar_close = bar_open + _td(seconds=120)
                        # If the bar Pine "saw" was actually the prior one
                        # (delivery slack means a bar may still be forming
                        # when the webhook arrives), clip non-negative.
                        tv_latency_seconds = round(
                            max(0.0, (webhook_received_at - bar_close).total_seconds()), 3,
                        )
            except Exception:
                tv_latency_seconds = None

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
            # 7-day TTL so last-known levels survive weekends + holiday closes
            # (markets can be dark ~65-90h). The compare page's staleness badge
            # flags them as not-live; a fresh push overwrites this anyway.
            rdb.setex(f"tv:levels:{ticker}", 604800, json.dumps(store))
            return jsonify({"status": "ok", "action": "levels_sync", "ticker": ticker})

        trade_type = data.get("type", "options")  # "options" or "futures"
        spread_pref = data.get("spread_type", "credit")
        override_contracts = data.get("contracts", 1)
        dte = data.get("dte", 0)

        # Per-strategy contract cap from user settings. Pine may send any
        # contracts value (default 1) but the user's settings define the
        # hard cap per strategy. Webhook is single-tenant — user 1.
        # Bug observed 2026-06-01: Pine fired 5+ separate 2n20 alerts that
        # accumulated to +5 MES, despite settings showing Contracts/Entry=1.
        # Pine sent 1 per signal (correct) but nothing was capping
        # aggregate. The hard cap below clamps per-order contracts; the
        # signal accumulation problem is separate (Pine-rate-limit).
        if trade_type == "futures":
            try:
                _u = User.query.get(1)
                if _u is not None:
                    if strategy in ("orb_butterfly", "orb"):
                        _cap = int(_u.orb_futures_contracts or 1)
                    else:
                        _cap = int(_u.futures_contracts or 1)
                    if int(override_contracts) > _cap:
                        logger.warning(
                            "futures cap: %s clamped %s -> %s (user setting)",
                            strategy, override_contracts, _cap)
                        override_contracts = _cap
            except Exception as _e:
                logger.warning("futures cap lookup failed: %s", _e)

        # ─── ORB BUTTERFLY PATH (SPX 0DTE leg-in) ───
        # Pine alert carries the full butterfly plan (K1/K2/K3, debit/credit
        # targets, OR context, VIX, reversal flag). Hand off to the dedicated
        # state machine in orb_butterfly_handler.
        if strategy == "orb_butterfly":
            # ORB source guard: when the native generator owns ORB, ignore TV's
            # butterfly alert (record it first for parity). Mirrors futures_2n20.
            try:
                _ro = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
                _osrc = _ro.get("ibkr:orb:source")
                _osrc = _osrc.decode().strip().lower() if _osrc else "tradingview"
                _ro.lpush("ibkr:orb:tv", json.dumps({
                    "leg": "butterfly", "direction": direction, "strategy": strategy,
                    "spread_type": data.get("spread_type"),
                    "received_at": datetime.now(timezone.utc).isoformat()}))
                _ro.ltrim("ibkr:orb:tv", 0, 99)
            except Exception:
                _osrc = "tradingview"
            if _osrc in ("native", "off"):
                logger.info("orb_butterfly ignored — source=%s", _osrc)
                return jsonify({"status": "skipped", "reason": f"orb_source_{_osrc}",
                                "strategy": strategy}), 200

            # Hard #5 (audit): restart-safety gate. Refuse butterflies
            # until ibkr-sync has reconciled — same as the futures path.
            try:
                from lumisignals import reconcile_gate
                if reconcile_gate.is_locked():
                    state = reconcile_gate.get_state()
                    logger.warning("reconcile_gate BLOCKED orb_butterfly %s: status=%s",
                                   ticker, state.get("status"))
                    return jsonify({
                        "status": "skipped",
                        "reason": "reconcile_gate_locked",
                        "gate_status": state.get("status"),
                        "ticker": ticker,
                    }), 503
            except Exception as e:
                logger.warning("reconcile_gate check failed (fail-closed): %s", e)
                return jsonify({
                    "status": "skipped",
                    "reason": "reconcile_gate_check_failed",
                    "ticker": ticker,
                }), 503
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

            # Source guard: when the native MES 2n20 generator owns the signal
            # (ibkr:mes_2n20:source = native/off), ignore TradingView's 2n20
            # alerts entirely so the two can't double-trade or fight over the
            # same position. Only 2n20 variants are gated — ORB et al. unaffected.
            if strategy.startswith("futures_2n20"):
                # Parity log — record EVERY TV 2n20 alert (acted on OR ignored)
                # with the bar it fired on, so the native signal stream
                # (ibkr:mes_2n20:native) can be diffed against TradingView.
                try:
                    _bt = None
                    _braw = rdb.get(f"ibkr:bars:{ticker}:2m")
                    if _braw:
                        _bars = json.loads(_braw).get("bars", [])
                        if _bars:
                            _bt = _bars[-1].get("time")
                    rdb.lpush("ibkr:mes_2n20:tv", json.dumps({
                        "kind": "ENTRY" if direction in ("BUY", "SELL") else "EXIT",
                        "direction": direction, "strategy": strategy, "bar_time": _bt,
                        "received_at": datetime.now(timezone.utc).isoformat(),
                    }))
                    rdb.ltrim("ibkr:mes_2n20:tv", 0, 199)
                except Exception:
                    pass

                try:
                    _src = rdb.get("ibkr:mes_2n20:source")
                    _src = _src.decode().strip().lower() if _src else "tradingview"
                except Exception:
                    _src = "tradingview"
                if _src in ("native", "off"):
                    logger.info("futures_2n20 %s %s ignored — source=%s",
                                direction, ticker, _src)
                    return jsonify({"status": "skipped",
                                    "reason": f"source_{_src}",
                                    "strategy": strategy, "ticker": ticker,
                                    "direction": direction}), 200

            # ORB source guard (MES breakout leg) — mirror of the butterfly
            # guard above so native owns the whole ORB trigger. Record the TV
            # alert for parity, then skip when native/off.
            if strategy.startswith("orb"):
                try:
                    rdb.lpush("ibkr:orb:tv", json.dumps({
                        "leg": "mes", "direction": direction, "strategy": strategy,
                        "stop_price": data.get("stop_price"),
                        "received_at": datetime.now(timezone.utc).isoformat()}))
                    rdb.ltrim("ibkr:orb:tv", 0, 99)
                    _osrc = rdb.get("ibkr:orb:source")
                    _osrc = _osrc.decode().strip().lower() if _osrc else "tradingview"
                except Exception:
                    _osrc = "tradingview"
                if _osrc in ("native", "off"):
                    logger.info("%s %s %s ignored — source=%s",
                                strategy, direction, ticker, _osrc)
                    return jsonify({"status": "skipped",
                                    "reason": f"orb_source_{_osrc}",
                                    "strategy": strategy, "ticker": ticker,
                                    "direction": direction}), 200

            # Restart-safety gate — refuse ALL futures signals (including
            # closes) until ibkr-sync has completed at least one reconcile
            # pass and is heart-beating. Without this, a webhook could land
            # between bot restart and the first state-sync, and we'd act on
            # stale strat_pos / diary state.
            try:
                from lumisignals import reconcile_gate
                if reconcile_gate.is_locked():
                    state = reconcile_gate.get_state()
                    logger.warning("reconcile_gate BLOCKED %s %s: status=%s",
                                   direction, ticker, state.get("status"))
                    return jsonify({
                        "status": "skipped",
                        "reason": "reconcile_gate_locked",
                        "gate_status": state.get("status"),
                        "gate_reason": state.get("reason"),
                        "ticker": ticker, "direction": direction,
                    }), 503
            except Exception as e:
                # Fail-CLOSED on gate errors. The whole point of this gate
                # is to prevent action on uncertain state — if we can't
                # verify, we refuse rather than assume safe.
                logger.warning("reconcile_gate check failed (fail-closed): %s", e)
                return jsonify({
                    "status": "skipped",
                    "reason": "reconcile_gate_check_failed",
                    "ticker": ticker, "direction": direction,
                }), 503

            # Daily-loss kill switch — only blocks new ENTRIES. Closes still
            # process so existing positions can exit normally. The bracket SL
            # at IB is the per-trade safety net; this is the per-day ceiling.
            if direction in ("BUY", "SELL"):
                try:
                    from lumisignals import kill_switch
                    if kill_switch.is_blocking_entry():
                        st = kill_switch.get_state()
                        cfg = kill_switch.get_config()
                        logger.warning(
                            "kill switch BLOCKED %s %s: day_pnl=$%.2f threshold=-$%.2f",
                            direction, ticker, st.get("day_pnl", 0.0),
                            cfg.get("threshold_usd", 250.0),
                        )
                        return jsonify({
                            "status": "skipped",
                            "reason": "kill_switch_tripped",
                            "day_pnl": round(st.get("day_pnl", 0.0), 2),
                            "threshold_usd": cfg.get("threshold_usd", 250.0),
                            "tripped_at": st.get("tripped_at"),
                            "ticker": ticker, "direction": direction,
                        }), 200
                except Exception as e:
                    # Don't let a kill-switch failure block trading. Log and
                    # continue — fail-open is the safer default given the
                    # bracket SL is still in place per-trade.
                    logger.warning("kill switch check failed (fail-open): %s", e)

            # CME futures maintenance window: 17:00–18:00 ET daily, all
            # weekdays. Pine's 2n20 script gates this server-side too
            # (`inSession`), but a TV alert with a stale chart timezone
            # or a misconfigured strategy could still fire into the
            # window. Refusing here is belt + suspenders. Soft #11.
            if direction in ("BUY", "SELL"):
                try:
                    from zoneinfo import ZoneInfo as _ZI
                    _now_et = datetime.now(timezone.utc).astimezone(_ZI("America/New_York"))
                    if _now_et.hour == 17:
                        logger.warning(
                            "CME maintenance window — refusing %s %s at %s ET",
                            direction, ticker, _now_et.strftime("%H:%M"),
                        )
                        return jsonify({
                            "status": "skipped",
                            "reason": "cme_maintenance_window",
                            "et_time": _now_et.strftime("%H:%M"),
                            "ticker": ticker, "direction": direction,
                        }), 503
                except Exception as _e:
                    # If timezone lookup fails for some reason, fall
                    # through — don't block trading on a tz library bug.
                    logger.warning("CME maintenance check failed: %s", _e)

            # Runaway guard — caps total accepted entries per day AND
            # consecutive losses streak. Independent of kill switch ($ loss
            # threshold) — guards against signal-frequency runaway and
            # whipsaw bleed. Closes are never blocked.
            if direction in ("BUY", "SELL"):
                try:
                    from lumisignals import runaway_guard
                    if runaway_guard.is_blocking_entry(strategy):
                        st = runaway_guard.get_state(strategy)
                        cfg = runaway_guard.get_config(strategy)
                        logger.warning(
                            "runaway_guard[%s] BLOCKED %s %s: %s",
                            strategy, direction, ticker, st.get("trip_reason"),
                        )
                        return jsonify({
                            "status": "skipped",
                            "reason": "runaway_guard_tripped",
                            "trip_reason": st.get("trip_reason"),
                            "trades_today": st.get("trades_today"),
                            "consecutive_losses": st.get("consecutive_losses"),
                            "max_trades_per_day": cfg.get("max_trades_per_day"),
                            "max_consecutive_losses": cfg.get("max_consecutive_losses"),
                            "tripped_at": st.get("tripped_at"),
                            "ticker": ticker, "direction": direction,
                        }), 200
                except Exception as e:
                    logger.warning("runaway_guard check failed (fail-open): %s", e)

            # Per-(strategy, ticker) cooldown — set by ibkr-sync when a
            # bracket SL fires. Refuses re-entry on the same level for the
            # configured cooldown period (default 2 min ~ 1 bar on a 2m
            # chart). Mirrors discretionary trader behaviour of waiting
            # after a stop before re-entering.
            if direction in ("BUY", "SELL"):
                try:
                    from lumisignals import cooldown
                    if cooldown.is_active(strategy, ticker):
                        ttl = cooldown.ttl(strategy, ticker)
                        logger.warning(
                            "cooldown BLOCKED %s %s [%s]: %ds remaining",
                            direction, ticker, strategy, ttl,
                        )
                        return jsonify({
                            "status": "skipped",
                            "reason": "cooldown_active",
                            "ttl_seconds": ttl,
                            "ticker": ticker, "direction": direction,
                            "strategy": strategy,
                        }), 200
                except Exception as e:
                    logger.warning("cooldown check failed (fail-open): %s", e)

            # Position size guard — refuse entries that would push projected
            # net contracts past the configured ceiling. Defense against
            # runaway loops or duplicate signals from stacking too many
            # contracts. Closes are never blocked (they reduce exposure).
            if direction in ("BUY", "SELL"):
                try:
                    from lumisignals import position_guard
                    pg_result = position_guard.check(ticker, direction, int(override_contracts or 1))
                    if pg_result.get("blocked"):
                        logger.warning(
                            "position guard BLOCKED %s %s contracts=%s: current=%s projected=%s limit=%s",
                            direction, ticker, pg_result.get("contracts"),
                            pg_result.get("current_net"),
                            pg_result.get("projected_net"),
                            pg_result.get("limit"),
                        )
                        return jsonify({
                            "status": "skipped",
                            "reason": "position_size_guard",
                            "ticker": ticker, "direction": direction,
                            "current_net": pg_result.get("current_net"),
                            "projected_net": pg_result.get("projected_net"),
                            "limit": pg_result.get("limit"),
                        }), 200
                except Exception as e:
                    logger.warning("position guard check failed (fail-open): %s", e)

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
            # Latency telemetry — threaded into the diary's INTENT_OPEN row
            # by ibkr-sync.
            order["webhook_received_at"] = webhook_received_at.isoformat()
            if tv_latency_seconds is not None:
                order["tv_latency_seconds"] = tv_latency_seconds
            rdb.setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))
            # Runaway guard: increment the daily trade counter after a
            # successful entry queue. This is what trips the cap when
            # Pine fires too many signals.
            try:
                from lumisignals import runaway_guard
                runaway_guard.record_entry(strategy)
            except Exception as _e:
                logger.warning("runaway_guard record_entry failed: %s", _e)
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
        # Hard #5 (audit): restart-safety gate. Refuse options until ibkr-sync
        # has reconciled — same as the futures path. Bot crash mid-trade
        # could leave stale options strat_pos that the gate prevents acting on.
        try:
            from lumisignals import reconcile_gate
            if reconcile_gate.is_locked():
                state = reconcile_gate.get_state()
                logger.warning("reconcile_gate BLOCKED options %s %s: status=%s",
                               direction, ticker, state.get("status"))
                return jsonify({
                    "status": "skipped",
                    "reason": "reconcile_gate_locked",
                    "gate_status": state.get("status"),
                    "ticker": ticker, "direction": direction,
                }), 503
        except Exception as e:
            logger.warning("reconcile_gate check failed (fail-closed): %s", e)
            return jsonify({
                "status": "skipped",
                "reason": "reconcile_gate_check_failed",
                "ticker": ticker, "direction": direction,
            }), 503

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
