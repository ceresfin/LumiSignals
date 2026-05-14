"""Standalone bot runner — runs outside gunicorn as its own process.

Checks the database for users with bot_active=True and runs their bots.
Stores watchlist data in Redis so the web app can read it.
"""

import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(__file__))

import redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bot_runner")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://lumisignals:LumiBot2026@localhost/lumisignals_db",
)

rdb = redis.from_url(REDIS_URL)


def get_active_users():
    """Query database for users with bot_active=True."""
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, email, oanda_account_id, oanda_api_key, oanda_environment,
               massive_api_key, trading_timeframe, min_score, min_risk_reward,
               stock_atr_multiplier, dry_run,
               scalp_risk_mode, scalp_risk_value, scalp_daily_budget,
               intraday_risk_mode, intraday_risk_value, intraday_daily_budget,
               swing_risk_mode, swing_risk_value, swing_daily_budget,
               lumitrade_api_key,
               scalp_min_score, scalp_min_rr, scalp_atr_multiplier,
               intraday_min_score, intraday_min_rr, intraday_atr_multiplier,
               swing_min_score, swing_min_rr, swing_atr_multiplier,
               dry_run_stocks,
               options_auto_trade, options_auto_spread_type, options_trigger_tf, options_min_verdict,
               options_max_risk_per_spread, options_max_contracts,
               options_max_total_risk, options_spread_width,
               options_min_credit_pct, options_max_spreads
        FROM users WHERE bot_active = true AND oanda_api_key IS NOT NULL
    """)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


def publish_watchlist(user_id, zones):
    """Store combined watchlist in Redis."""
    rdb.setex(f"watchlist:{user_id}", 600, json.dumps(zones))


def publish_watchlist_model(user_id, model_name, zones):
    """Store per-model watchlist in Redis."""
    rdb.setex(f"watchlist:{user_id}:{model_name}", 600, json.dumps(zones))
    # Also update combined
    all_zones = []
    for mn in ["scalp", "intraday", "swing"]:
        raw = rdb.get(f"watchlist:{user_id}:{mn}")
        if raw:
            all_zones.extend(json.loads(raw))
    rdb.setex(f"watchlist:{user_id}", 600, json.dumps(all_zones))


def publish_log(user_id, entries):
    """Store log entries in Redis."""
    rdb.setex(f"botlog:{user_id}", 600, json.dumps(entries[-100:]))


def _auto_trade_options(user_data, signal, extra_meta, model_name, log, alert_pass, email, model_cfg=None):
    """Analyze and queue options spread when a stock signal fires."""
    from datetime import datetime as _dt, timezone, timedelta
    from lumisignals.polygon_options import analyze_spreads_polygon
    from lumisignals.options_sizing import OptionsRiskConfig, calculate_spread_contracts

    user_id = user_data["id"]
    symbol = signal.symbol
    zone_type = (extra_meta or {}).get("zone_type", "demand" if signal.action == "BUY" else "supply")
    zone_price = (extra_meta or {}).get("zone_price", signal.entry)
    spread_pref = user_data.get("options_auto_spread_type") or "credit"
    min_verdict = user_data.get("options_min_verdict") or "good"
    allowed_verdicts = ["GOOD"] if min_verdict == "good" else ["GOOD", "FAIR"]

    massive_key = user_data.get("massive_api_key") or os.environ.get("MASSIVE_API_KEY", "")
    if not massive_key:
        log(f"[{model_name.upper()}] OPTIONS: No Polygon API key — skipping")
        return

    # Deduplication — check if we already have an order/position for this ticker + zone
    today = _dt.now(timezone.utc).strftime("%Y-%m-%d")
    zone_tf = (extra_meta or {}).get("zone_timeframe", "")
    dedup_key = f"traded:{user_id}:{symbol}:{zone_tf}_{zone_type}:{today}"
    existing = rdb.get(dedup_key)
    if existing:
        log(f"[{model_name.upper()}] OPTIONS: {symbol} already traded at {zone_tf} {zone_type} today — skipping")
        return

    # Also check if there's already an open position or pending order for this ticker
    for key in rdb.scan_iter(f"ibkr:order:pending:*"):
        raw = rdb.get(key)
        if raw:
            order = json.loads(raw)
            if order.get("ticker") == symbol and order.get("status") in ("queued", "placing", "PreSubmitted", "Submitted"):
                log(f"[{model_name.upper()}] OPTIONS: {symbol} already has a pending order — skipping")
                return

    # Build risk config from user settings
    risk_config = OptionsRiskConfig(
        max_risk_per_spread=float(user_data.get("options_max_risk_per_spread") or 200),
        max_contracts=int(user_data.get("options_max_contracts") or 5),
        max_total_risk=float(user_data.get("options_max_total_risk") or 2000),
        spread_width=float(user_data.get("options_spread_width") or 5),
        min_credit_pct=float(user_data.get("options_min_credit_pct") or 25),
        max_spreads=int(user_data.get("options_max_spreads") or 10),
    )

    # Model-specific DTE ranges — from ModelConfig or fallback
    if model_cfg and model_cfg.options_dte_range:
        min_dte, max_dte = model_cfg.options_dte_range
    else:
        _dte_fallback = {"scalp": (3, 7), "intraday": (7, 14), "swing": (25, 40)}
        min_dte, max_dte = _dte_fallback.get(model_name, (25, 40))

    log(f"[{model_name.upper()}] OPTIONS: Analyzing {symbol} ({zone_type} zone @ {zone_price:.2f}, DTE {min_dte}-{max_dte}d)")

    # Run Polygon analysis
    try:
        result = analyze_spreads_polygon(
            massive_key, symbol, zone_type, zone_price, signal.entry,
            max_risk_per_spread=risk_config.max_risk_per_spread,
            preferred_width=risk_config.spread_width,
            min_dte=min_dte, max_dte=max_dte,
        )
    except Exception as e:
        log(f"[{model_name.upper()}] OPTIONS: Polygon analysis failed — {e}")
        return

    if result.get("error"):
        log(f"[{model_name.upper()}] OPTIONS: Analysis error — {result['error']}")
        return

    credit = result.get("credit_spread")
    debit = result.get("debit_spread")
    log(f"[{model_name.upper()}] OPTIONS: {symbol} — credit: {credit.get('verdict') if credit else 'none'}, debit: {debit.get('verdict') if debit else 'none'}")

    orders_queued = []

    # Process credit spread
    credit = result.get("credit_spread")
    if credit and spread_pref in ("credit", "both"):
        if credit.get("verdict") in allowed_verdicts:
            is_credit = credit["net_credit"] > 0
            premium = credit["net_credit"] if is_credit else credit["net_debit"]
            width = credit["width"]

            sizing = calculate_spread_contracts(
                spread_width=width, credit_or_debit=premium,
                is_credit=is_credit, risk_config=risk_config,
            )

            if sizing["contracts"] > 0:
                import uuid
                from datetime import datetime as _dt
                order_id = str(uuid.uuid4())[:8]
                order = {
                    "order_id": order_id,
                    "queued_at": _dt.now(timezone.utc).isoformat(),
                    "user_id": user_id,
                    "ticker": symbol,
                    "spread_type": credit["type"],
                    "buy_strike": credit["long_strike"],
                    "sell_strike": credit["short_strike"],
                    "right": "C" if "Call" in credit["option_type"] else "P",
                    "expiration": credit["expiration"],
                    "quantity": sizing["contracts"],
                    "limit_price": premium,
                    "is_credit": True,
                    "width": width,
                    "max_risk": sizing["total_risk"],
                    "max_profit": sizing["max_profit"],
                    "risk_reward": credit["risk_reward"],
                    "verdict": credit["verdict"],
                    "status": "queued",
                    "auto": True,
                    "model": model_name,
                    "strategy": "htf_levels",
                    "zone_type": zone_type,
                    "zone_price": zone_price,
                    "trigger_pattern": (extra_meta or {}).get("trigger_pattern", ""),
                    "bias_score": (extra_meta or {}).get("bias_score", 0),
                    "zone_timeframe": (extra_meta or {}).get("zone_timeframe", ""),
                    "signal_action": signal.action,
                    "signal_entry": signal.entry,
                }
                rdb.setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))
                orders_queued.append(f"{credit['type']} {sizing['contracts']}x @ ${premium:.2f}")
                log(f"[{model_name.upper()}] OPTIONS QUEUED: {credit['type']} {symbol} SELL {credit['short_strike']} / BUY {credit['long_strike']} x{sizing['contracts']} @ ${premium:.2f} (risk ${sizing['total_risk']:.0f})")
            else:
                log(f"[{model_name.upper()}] OPTIONS SKIP: {credit['type']} — {sizing.get('reason', 'sizing rejected')}")
        else:
            log(f"[{model_name.upper()}] OPTIONS SKIP: {credit['type']} — verdict: {credit.get('verdict')}")

    # Process debit spread
    debit = result.get("debit_spread")
    if debit and spread_pref in ("debit", "both"):
        if debit.get("verdict") in allowed_verdicts:
            is_credit = False
            premium = debit["net_debit"]
            width = debit["width"]

            sizing = calculate_spread_contracts(
                spread_width=width, credit_or_debit=premium,
                is_credit=False, risk_config=risk_config,
            )

            if sizing["contracts"] > 0:
                import uuid
                from datetime import datetime as _dt
                order_id = str(uuid.uuid4())[:8]
                order = {
                    "order_id": order_id,
                    "queued_at": _dt.now(timezone.utc).isoformat(),
                    "user_id": user_id,
                    "ticker": symbol,
                    "spread_type": debit["type"],
                    "buy_strike": debit["long_strike"],
                    "sell_strike": debit["short_strike"],
                    "right": "C" if "Call" in debit["option_type"] else "P",
                    "expiration": debit["expiration"],
                    "quantity": sizing["contracts"],
                    "limit_price": premium,
                    "is_credit": False,
                    "width": width,
                    "max_risk": sizing["total_risk"],
                    "max_profit": sizing["max_profit"],
                    "risk_reward": debit["risk_reward"],
                    "verdict": debit["verdict"],
                    "status": "queued",
                    "auto": True,
                    "model": model_name,
                    "strategy": "htf_levels",
                    "zone_type": zone_type,
                    "zone_price": zone_price,
                    "trigger_pattern": (extra_meta or {}).get("trigger_pattern", ""),
                    "bias_score": (extra_meta or {}).get("bias_score", 0),
                    "zone_timeframe": (extra_meta or {}).get("zone_timeframe", ""),
                    "signal_action": signal.action,
                    "signal_entry": signal.entry,
                }
                rdb.setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))
                orders_queued.append(f"{debit['type']} {sizing['contracts']}x @ ${premium:.2f}")
                log(f"[{model_name.upper()}] OPTIONS QUEUED: {debit['type']} {symbol} BUY {debit['long_strike']} / SELL {debit['short_strike']} x{sizing['contracts']} @ ${premium:.2f} (risk ${sizing['total_risk']:.0f})")
            else:
                log(f"[{model_name.upper()}] OPTIONS SKIP: {debit['type']} — {sizing.get('reason', 'sizing rejected')}")
        else:
            log(f"[{model_name.upper()}] OPTIONS SKIP: {debit['type']} — verdict: {debit.get('verdict')}")

    # Alert on queued orders
    if orders_queued and alert_pass:
        from lumisignals.alerts import send_alert, AlertType
        send_alert(
            AlertType.TRADE_OPENED,
            f"Options queued: {symbol}",
            f"Stock signal triggered auto-options analysis. Orders queued for IB:\n" + "\n".join(orders_queued),
            details={
                "Symbol": symbol,
                "Zone": f"{zone_type} @ {zone_price:.2f}",
                "Signal": f"{signal.action} @ {signal.entry:.2f}",
                "Orders": ", ".join(orders_queued),
            },
            to_email=email, smtp_pass=alert_pass,
        )

    # Mark this ticker+zone as traded today (expires at midnight UTC + 24h buffer)
    if orders_queued:
        rdb.setex(dedup_key, 86400, json.dumps({
            "symbol": symbol,
            "zone": f"{zone_tf} {zone_type}",
            "model": model_name,
            "orders": orders_queued,
            "traded_at": _dt.now(timezone.utc).isoformat(),
        }))


def run_bot_for_user(user_data, stop_check):
    """Run the three-phase signal engine for a user."""
    from lumisignals.oanda_client import OandaClient
    from lumisignals.snr_filter import SNRClient
    from lumisignals.levels_strategy import LevelsStrategy, get_watchlist_snapshot
    from lumisignals.massive_client import MassiveClient, DEFAULT_TICKERS
    from lumisignals.signal_log import SignalLog

    user_id = user_data["id"]
    email = user_data["email"]
    log_entries = []

    def log(msg):
        from datetime import datetime, timezone, timedelta
        et = datetime.now(timezone.utc) + timedelta(hours=-4)
        entry = f"{et.strftime('%I:%M:%S %p')} {msg}"
        log_entries.append(entry)
        if len(log_entries) > 200:
            del log_entries[:100]
        publish_log(user_id, log_entries)
        logger.info("[user:%s] %s", email, msg)

    log("Bot starting...")

    oanda = OandaClient(
        account_id=user_data["oanda_account_id"],
        api_key=user_data["oanda_api_key"],
        environment=user_data.get("oanda_environment") or "practice",
    )

    if not user_data.get("dry_run", True):
        if not oanda.validate_connection():
            log("Could not connect to Oanda — check credentials")
            return
        log("Connected to Oanda")
    else:
        log("Dry-run mode — skipping Oanda validation")

    snr_base_url = "https://app.lumitrade.ai/api/v1"
    snr_api_key = user_data.get("lumitrade_api_key") or os.environ.get("LUMITRADE_API_KEY", "")
    snr = SNRClient(base_url=snr_base_url, api_key=snr_api_key)

    massive = None
    stock_tickers = []
    massive_key = user_data.get("massive_api_key") or os.environ.get("MASSIVE_API_KEY", "")
    if massive_key:
        massive = MassiveClient(api_key=massive_key)
        stock_tickers = list(DEFAULT_TICKERS)
        log(f"Massive connected — scanning {len(stock_tickers)} stock/crypto tickers")

    signal_log = SignalLog(path=f"/opt/lumisignals/signal_log_user_{user_id}.json")

    def on_signal(signal, extra_meta=None):
        log(f"SIGNAL: {signal.action} {signal.symbol} @ {signal.entry:.5f} | R:R {signal.risk_reward:.1f}")
        log_entry = {
            "action": signal.action, "symbol": signal.symbol,
            "entry": signal.entry, "stop": signal.stop, "target": signal.target,
            "risk_reward": signal.risk_reward,
        }
        if extra_meta:
            log_entry.update(extra_meta)
        signal_log.record(f"{signal.symbol}_{int(time.time())}", log_entry)

    from lumisignals.levels_strategy import SCALP_MODEL, INTRADAY_MODEL, SWING_MODEL, ALL_MODELS
    from lumisignals.risk_budget import record_loss, is_budget_exceeded
    from lumisignals.alerts import alert_signal, alert_trade_opened, alert_budget_hit

    alert_pass = os.environ.get("ALERT_EMAIL_PASSWORD", "")

    import threading

    def get_risk_config(user_data, model_name, model_cfg):
        """Build risk config dict from user settings, falling back to ModelConfig defaults."""
        mode = user_data.get(f"{model_name}_risk_mode") or "percent"
        value = user_data.get(f"{model_name}_risk_value")
        if value is None:
            value = model_cfg.risk_percent
        config = {"max_open_positions": 999}
        if mode == "fixed":
            config["risk_percent"] = 0
            config["risk_dollar"] = float(value)
        else:
            config["risk_percent"] = float(value)
            config["risk_dollar"] = 0.0
        return config

    # Apply per-model user settings to model configs
    from copy import copy
    user_models = []
    for base_cfg in [SCALP_MODEL, INTRADAY_MODEL, SWING_MODEL]:
        cfg = copy(base_cfg)
        name = cfg.name
        user_score = user_data.get(f"{name}_min_score")
        user_rr = user_data.get(f"{name}_min_rr")
        user_atr = user_data.get(f"{name}_atr_multiplier")
        if user_score is not None:
            cfg.min_score = int(user_score)
        if user_rr is not None:
            cfg.min_risk_reward = float(user_rr)
        if user_atr is not None:
            cfg.atr_stop_multiplier = float(user_atr)
        # Apply options trigger TF if auto-trade is enabled
        if user_data.get("options_auto_trade"):
            cfg.options_trigger_tf = user_data.get("options_trigger_tf") or "4h"
        user_models.append(cfg)

    # Create all three model strategies
    models = {}
    for model_cfg in user_models:
        def make_signal_handler(model_name, _model_cfg=model_cfg):
            risk_cfg = get_risk_config(user_data, model_name, _model_cfg)
            daily_budget = float(user_data.get(f"{model_name}_daily_budget") or 0)
            risk_mode = user_data.get(f"{model_name}_risk_mode") or "percent"
            risk_val = risk_cfg.get("risk_dollar") if risk_mode == "fixed" else risk_cfg.get("risk_percent")
            log(f"[{model_name.upper()}] Risk: {risk_mode} {'$' if risk_mode == 'fixed' else ''}{risk_val}{'%' if risk_mode == 'percent' else ''} | Daily budget: {'$' + str(daily_budget) if daily_budget > 0 else 'unlimited'}")

            def handler(signal, extra_meta=None):
                log(f"[{model_name.upper()}] SIGNAL: {signal.action} {signal.symbol} @ {signal.entry:.5f} | R:R {signal.risk_reward:.1f}")
                log_entry = {
                    "action": signal.action, "symbol": signal.symbol,
                    "entry": signal.entry, "stop": signal.stop, "target": signal.target,
                    "risk_reward": signal.risk_reward,
                    "strategy_id": "htf_levels", "model": model_name,
                }
                if extra_meta:
                    log_entry.update(extra_meta)
                signal_log.record(f"{model_name}_{signal.symbol}_{int(time.time())}", log_entry)

                # Email alert for every signal
                if alert_pass:
                    try:
                        alert_signal(
                            model=model_name, action=signal.action, symbol=signal.symbol,
                            entry=signal.entry, risk_reward=signal.risk_reward,
                            score=extra_meta.get("bias_score", 0) if extra_meta else 0,
                            stop=signal.stop, target=signal.target,
                            zone_type=extra_meta.get("zone_type", "") if extra_meta else "",
                            zone_timeframe=extra_meta.get("zone_timeframe", "") if extra_meta else "",
                            trigger_pattern=extra_meta.get("trigger_pattern", "") if extra_meta else "",
                            to_email=email, smtp_pass=alert_pass,
                        )
                    except Exception as e:
                        logger.debug("Alert error: %s", e)

                # --- Auto-trade options for stock signals ---
                is_stock = extra_meta and extra_meta.get("is_stock")
                auto_trade = user_data.get("options_auto_trade", False)
                if is_stock and auto_trade:
                    try:
                        _auto_trade_options(
                            user_data, signal, extra_meta, model_name,
                            log, alert_pass, email, model_cfg=_model_cfg,
                        )
                    except Exception as e:
                        log(f"[{model_name.upper()}] OPTIONS AUTO-TRADE ERROR: {e}")
                        logger.error("Options auto-trade error: %s", e)

                # Skip forex execution for stock signals (stocks go through options, not Oanda)
                if is_stock:
                    return

                if not user_data.get("dry_run", True):
                    # Check daily budget before placing order
                    if daily_budget > 0 and is_budget_exceeded(user_id, model_name, daily_budget):
                        log(f"[{model_name.upper()}] SKIPPED — daily loss budget ${daily_budget:.0f} exceeded")
                        if alert_pass:
                            try:
                                from lumisignals.risk_budget import get_daily_loss
                                spent = get_daily_loss(user_id, model_name)
                                alert_budget_hit(model_name, daily_budget, spent, to_email=email, smtp_pass=alert_pass)
                            except Exception:
                                pass
                        return

                    from lumisignals.order_manager import OrderManager
                    om = OrderManager(client=oanda, risk_config=risk_cfg, dry_run=False)
                    result = om.execute_signal(signal)
                    if result.success:
                        log(f"[{model_name.upper()}] ORDER PLACED: {result.order_id}")
                        # Email alert for trade placed
                        if alert_pass:
                            try:
                                alert_trade_opened(
                                    model=model_name, action=signal.action, symbol=signal.symbol,
                                    units=result.details.get("units", 0) if result.details else 0,
                                    entry=signal.entry, order_id=result.order_id,
                                    risk_amount=risk_cfg.get("risk_dollar") or (result.details.get("balance", 0) * risk_cfg.get("risk_percent", 0) / 100) if result.details else 0,
                                    to_email=email, smtp_pass=alert_pass,
                                )
                            except Exception as e:
                                logger.debug("Trade alert error: %s", e)
                        # Record risk amount against daily budget
                        risk_amt = risk_cfg.get("risk_dollar") or 0
                        if risk_amt <= 0 and result.details:
                            bal = result.details.get("balance", 0)
                            risk_amt = bal * (risk_cfg.get("risk_percent", 0) / 100)
                        if risk_amt > 0:
                            record_loss(user_id, model_name, risk_amt)
                        # Also record under Oanda order ID for trade enrichment
                        signal_log.record(result.order_id, log_entry)
                        try:
                            signal_log.record(str(int(result.order_id) + 1), log_entry)
                        except (ValueError, TypeError):
                            pass

                        # Telegram + push alert with the full HTF plan
                        try:
                            from lumisignals.supabase_client import notify_trade_opened
                            supabase_uid_n = os.environ.get("SUPABASE_USER_ID", "")
                            if supabase_uid_n:
                                bal = (result.details or {}).get("balance", 0)
                                risk_amt_n = risk_cfg.get("risk_dollar") or (bal * (risk_cfg.get("risk_percent", 0) / 100))
                                rr_n = signal.risk_reward or 0
                                reward_amt_n = risk_amt_n * rr_n if (risk_amt_n and rr_n) else None
                                notify_trade_opened(
                                    user_id=supabase_uid_n,
                                    instrument=signal.symbol,
                                    direction=signal.action,
                                    entry_price=signal.entry,
                                    strategy=f"{model_name.upper()} HTF",
                                    stop=signal.stop,
                                    target=signal.target,
                                    risk_dollars=risk_amt_n or None,
                                    reward_dollars=reward_amt_n,
                                    rr_ratio=rr_n or None,
                                )
                        except Exception as e:
                            logger.debug("HTF Telegram alert error: %s", e)

                        # Pre-save HTF position to Supabase with entry/stop/target +
                        # zone metadata (zone type, timeframe, score, trends) so the
                        # mobile app can show Risk/Reward AND the originating zone
                        # context on every active position card.
                        if result.trade_id:
                            try:
                                from lumisignals.supabase_client import upsert_position
                                supabase_uid = os.environ.get("SUPABASE_USER_ID", "")
                                if supabase_uid:
                                    from datetime import datetime as _dt, timezone as _tz
                                    # Zone metadata comes from extra_meta — same shape
                                    # the signal_log records.
                                    meta = {}
                                    if extra_meta:
                                        meta = {
                                            "zone_type": extra_meta.get("zone_type") or extra_meta.get("level_type", ""),
                                            "zone_timeframe": extra_meta.get("zone_timeframe") or extra_meta.get("level_timeframe", ""),
                                            "zone_price": extra_meta.get("zone_price") or extra_meta.get("level_price", 0),
                                            "bias_score": extra_meta.get("bias_score") or extra_meta.get("final_score", 0),
                                            "trigger_pattern": extra_meta.get("trigger_pattern", ""),
                                            "trends": extra_meta.get("trends", {}),
                                        }
                                        # Drop empty values so the JSONB stays compact.
                                        meta = {k: v for k, v in meta.items() if v not in (None, "", 0, {})}
                                    upsert_position(supabase_uid, {
                                        "id": result.trade_id,
                                        "broker": "oanda",
                                        "instrument": signal.symbol,
                                        "asset_type": "forex",
                                        "direction": signal.action,
                                        "units": (result.details or {}).get("units", 0),
                                        "entry_price": signal.entry,
                                        "stop_loss": signal.stop,
                                        "take_profit": signal.target,
                                        "strategy": "htf_levels",
                                        "model": model_name,
                                        "opened_at": _dt.now(_tz.utc).isoformat(),
                                        "metadata": meta or None,
                                    })
                            except Exception as e:
                                log(f"[{model_name.upper()}] Supabase position pre-save failed: {e}")
                    else:
                        log(f"[{model_name.upper()}] ORDER FAILED: {result.error}")
            return handler

        strategy = LevelsStrategy(
            oanda_client=oanda, snr_client=snr,
            trade_builder_url=snr_base_url, api_key=snr_api_key,
            model=model_cfg,
            massive_client=massive, stock_tickers=stock_tickers,
            stock_atr_multiplier=user_data.get("stock_atr_multiplier") or 0.5,
            on_signal=make_signal_handler(model_cfg.name),
        )
        models[model_cfg.name] = strategy
        log(f"[{model_cfg.name.upper()}] Configured — zones: {model_cfg.zone_tfs}, trigger: {model_cfg.trigger_tf}, bias: {model_cfg.bias_tf}")

    # Patch each strategy's watchlist refresh to publish to Redis per model
    for model_name, strategy in models.items():
        original = strategy._refresh_watchlist
        mn = model_name  # capture for closure

        def make_patched(orig, name):
            def patched(pairs=None):
                orig(pairs)
                zones = get_watchlist_snapshot(name)
                publish_watchlist_model(user_id, name, zones)
                log(f"[{name.upper()}] Watchlist: {len(zones)} zones")
            return patched

        strategy._refresh_watchlist = make_patched(original, mn)

    opts_tf = user_data.get("options_trigger_tf") or "4h"
    if user_data.get("options_auto_trade"):
        log(f"Options auto-trade enabled — stock zones get extra trigger check at {opts_tf}")
    log("All 3 models running — SCALP (15m) + INTRADAY (1h) + SWING (daily)")

    # --- 2n20 FX Scalp Strategy ---
    fx_scalp = None
    if not user_data.get("dry_run", True):
        try:
            from lumisignals.fx_scalp_2n20 import FXScalp2n20
            fx_sl = float(user_data.get("futures_stop_loss", 25))

            def fx_signal_cb(sig):
                log(f"[2n20_FX] {sig.get('direction','')} {sig.get('instrument','')} — {sig.get('reason', sig.get('strategy',''))}")
                # Publish to Redis for trades page
                try:
                    import redis as _rdb
                    rdb = _rdb.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
                    import json as _json
                    from datetime import datetime as _dt2, timezone as _tz2
                    sig["timestamp"] = _dt2.now(_tz2.utc).isoformat()
                    rdb.lpush("fx_scalp_2n20:signals", _json.dumps(sig))
                    rdb.ltrim("fx_scalp_2n20:signals", 0, 99)
                except Exception:
                    pass

            # USD majors only — 7 pairs for fast scan cycles (~2-3 sec vs 18+ min for 28)
            ACTIVE_FX_PAIRS = [
                "EUR_USD", "USD_JPY",
            ]
            fx_scalp = FXScalp2n20(oanda, pairs=ACTIVE_FX_PAIRS, sl_dollars=fx_sl,
                                    signal_callback=fx_signal_cb, signal_log=signal_log)
            log(f"[2n20_FX] Scalp strategy active — {len(fx_scalp.pairs)} pairs, SL ${fx_sl}")
        except Exception as e:
            log(f"[2n20_FX] Setup error: {e}")

    # --- FX Intraday 4H Trend Strategy (paper launch) ---
    # Regime-gated 4H trend strategy validated at +$25K net over 24mo
    # backtest.  Reads regime:fx_4h:{pair} from Redis to know which
    # pairs are currently eligible; the weekly cron updates that state
    # every Sunday at the FX rollover.
    fx_4h = None
    if not user_data.get("dry_run", True) and os.environ.get("FX_4H_ENABLED", "true").lower() != "false":
        try:
            from lumisignals.fx_trend_4h import FXTrend4H

            def fx_4h_signal_cb(sig):
                log(f"[FX_4H] {sig.get('direction','')} {sig.get('instrument','')} "
                    f"@ {sig.get('entry', 0):.5f}  SL={sig.get('stop',0):.5f} "
                    f"TP={sig.get('target',0):.5f}")
                try:
                    import redis as _rdb
                    rdb = _rdb.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
                    import json as _json
                    from datetime import datetime as _dt2, timezone as _tz2
                    sig["timestamp"] = _dt2.now(_tz2.utc).isoformat()
                    rdb.lpush("fx_trend_4h:signals", _json.dumps(sig))
                    rdb.ltrim("fx_trend_4h:signals", 0, 99)
                except Exception:
                    pass

            fx_4h = FXTrend4H(oanda, signal_callback=fx_4h_signal_cb)
            log(f"[FX_4H] Trend strategy active — {len(fx_4h.pairs)} pairs, "
                f"risk ${fx_4h.risk_per_trade:.0f}/trade")
        except Exception as e:
            log(f"[FX_4H] Setup error: {e}")

    # --- 2n20 MES Futures Scalp (server-side) ---
    # Disabled by default: TradingView's Pine Script alert is the source for MES
    # signals because the IB account lacks a CME real-time market data subscription,
    # so internally-polled bars lag 2-3 min. TV fires on bar close in real-time
    # and POSTs to /api/webhook/tradingview. Set INTERNAL_MES_2N20=1 to re-enable.
    mes_scalp = None
    if massive_key and os.environ.get("INTERNAL_MES_2N20") == "1":
        try:
            from lumisignals.futures_scalp_2n20 import FuturesScalp2n20

            def mes_signal_cb(sig):
                log(f"[2n20_MES] {sig.get('direction','')} {sig.get('ticker','')} — {sig.get('reason', sig.get('strategy',''))}")

            contract_count = max(1, int(user_data.get("futures_contracts", 1) or 1))
            mes_scalp = FuturesScalp2n20(massive_key, signal_callback=mes_signal_cb,
                                          contract_count=contract_count)
            log(f"[2n20_MES] Server-side futures scalp active — MES via Polygon + IB ({contract_count} contracts/entry)")
        except Exception as e:
            log(f"[2n20_MES] Setup error: {e}")
    else:
        log("[2n20_MES] Internal strategy disabled — using TradingView webhook for MES signals")

    # ─── THREADED STRATEGY RUNNERS ─────────────────────────────────────
    # Each strategy runs in its own thread with its own loop speed.
    # They don't wait for each other — the 2n20 scalp fires every 10s
    # regardless of how long the HTF levels scan takes.
    import threading

    _stop_event = threading.Event()

    def run_2n20_thread():
        """Fast loop: 2n20 scalp strategies. Runs every 10 seconds."""
        log("[Thread-2n20] Started — scanning every 10s")
        while not _stop_event.is_set():
            if fx_scalp:
                try:
                    fx_scalp.scan_all()
                except Exception as e:
                    logger.debug("[2n20_FX] Scan error: %s", e)
            if mes_scalp:
                try:
                    mes_scalp.scan()
                except Exception as e:
                    logger.debug("[2n20_MES] Scan error: %s", e)
            _stop_event.wait(10)
        log("[Thread-2n20] Stopped")

    def run_fx_4h_thread():
        """Slow loop: FX 4H trend.  Polls every 60s; the strategy's own
        per-bar dedup ensures it only fires entries on newly closed 4H
        bars.  Exit checks (Friday flat, EMA invalidation) run every
        minute too — cheap, and means we don't sit on a stale state
        between 4H closes if the regime flips."""
        if fx_4h is None:
            return
        log("[Thread-FX4H] Started — polling every 60s")
        while not _stop_event.is_set():
            try:
                fx_4h.scan_all()
            except Exception as e:
                logger.debug("[FX_4H] Scan error: %s", e)
            _stop_event.wait(60)
        log("[Thread-FX4H] Stopped")

    def run_htf_thread():
        """Slow loop: HTF levels strategies. Each model runs at its own cadence."""
        log("[Thread-HTF] Started — levels strategies running independently")
        tick = 0
        MODEL_SCAN_CADENCE = {
            "scalp": 30,       # every 5 min (30 × 10s)
            "intraday": 90,    # every 15 min
            "swing": 8640,     # every 24 hr
        }
        while not _stop_event.is_set():
            for model_name, strategy in models.items():
                scan_cadence = MODEL_SCAN_CADENCE.get(model_name, 30)
                if tick % scan_cadence != 0:
                    continue

                ticks_per_wl = max(1, strategy.watchlist_interval // 30)
                if tick % ticks_per_wl == 0:
                    try:
                        strategy._refresh_watchlist()
                    except Exception as e:
                        logger.debug("[%s] Watchlist error: %s", model_name, e)

                try:
                    strategy._monitor_zones()
                except Exception as e:
                    logger.debug("[%s] Monitor error: %s", model_name, e)

                try:
                    strategy._check_triggers()
                except Exception as e:
                    logger.debug("[%s] Trigger error: %s", model_name, e)

                strategy._watchlist = [z for z in strategy._watchlist if z.status != "triggered"]

                zones = get_watchlist_snapshot(model_name)
                publish_watchlist_model(user_id, model_name, zones)

            tick += 1
            _stop_event.wait(10)
        log("[Thread-HTF] Stopped")

    def run_swing_thread():
        """Periodic: swing auto-scanner. Runs every 4 hours during market hours."""
        log("[Thread-Swing] Started — scanning every 4 hours")
        while not _stop_event.is_set():
            try:
                from lumisignals.swing_scanner import run_swing_scan, should_scan_now
                if should_scan_now():
                    import redis as _rdb_mod
                    swing_rdb = _rdb_mod.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
                    swing_massive_key = os.environ.get("MASSIVE_API_KEY", "")
                    if swing_massive_key and massive:
                        log("Running swing auto-scan...")
                        triggered = run_swing_scan(massive, swing_rdb, swing_massive_key)
                        if triggered:
                            log(f"Swing scan: {len(triggered)} trades triggered")
                        else:
                            log("Swing scan: no confirmed setups")
            except Exception as e:
                logger.debug("Swing scan error: %s", e)
            # Wait 4 hours (check every 60s if stop requested)
            for _ in range(240):
                if _stop_event.is_set():
                    break
                _stop_event.wait(60)
        log("[Thread-Swing] Stopped")

    # Start all threads
    threads = []
    if fx_scalp or mes_scalp:
        t = threading.Thread(target=run_2n20_thread, name="2n20", daemon=True)
        t.start()
        threads.append(t)

    if models:
        t = threading.Thread(target=run_htf_thread, name="HTF", daemon=True)
        t.start()
        threads.append(t)

    if fx_4h:
        t = threading.Thread(target=run_fx_4h_thread, name="FX4H", daemon=True)
        t.start()
        threads.append(t)

    t = threading.Thread(target=run_swing_thread, name="Swing", daemon=True)
    t.start()
    threads.append(t)

    log(f"All {len(threads)} strategy threads running")

    # Main thread: monitor for user deactivation
    while True:
        if stop_check(user_id):
            log("Bot stopped by user")
            _stop_event.set()
            break
        time.sleep(30)

    log("Bot stopped")


def check_user_inactive(user_id):
    """Check if user deactivated their bot."""
    import psycopg2
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT bot_active FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        conn.close()
        return not (row and row[0])
    except Exception:
        return False


def main():
    """Main loop — check for active users and run their bots."""
    import threading

    logger.info("Bot runner starting — checking for active users every 30s")
    active_threads = {}  # user_id → thread

    while True:
        try:
            users = get_active_users()
            active_ids = {u["id"] for u in users}

            # Start bots for new active users
            for user in users:
                uid = user["id"]
                if uid not in active_threads or not active_threads[uid].is_alive():
                    logger.info("Starting bot for user %s (%s)", uid, user["email"])
                    t = threading.Thread(
                        target=run_bot_for_user,
                        args=(user, check_user_inactive),
                        daemon=True,
                        name=f"bot-{uid}",
                    )
                    t.start()
                    active_threads[uid] = t

            # Clean up threads for deactivated users
            for uid in list(active_threads.keys()):
                if uid not in active_ids:
                    logger.info("User %s deactivated — bot will stop", uid)
                    active_threads.pop(uid, None)

        except Exception as e:
            logger.error("Bot runner error: %s", e)

        time.sleep(30)


if __name__ == "__main__":
    main()
