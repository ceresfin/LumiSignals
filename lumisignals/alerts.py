"""Email alert system for LumiSignals.

Sends alerts via Gmail SMTP for signals, trades, and system events.

Usage:
    from lumisignals.alerts import send_alert, AlertType

    send_alert(AlertType.SIGNAL, "BUY AAPL @ $270", user_email="sonia@example.com")
"""

import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from enum import Enum
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ.get("ALERT_EMAIL", "sonia.spirling@gmail.com")
SMTP_PASS = os.environ.get("ALERT_EMAIL_PASSWORD", "")


class AlertType(Enum):
    SIGNAL = "signal"
    TRADE_OPENED = "trade_opened"
    TRADE_CLOSED = "trade_closed"
    BUDGET_HIT = "budget_hit"
    TOKEN_EXPIRY = "token_expiry"
    BOT_ERROR = "bot_error"
    BOT_STATUS = "bot_status"


# Styling per alert type
ALERT_CONFIG = {
    AlertType.SIGNAL: {
        "subject_prefix": "Signal",
        "color": "#7F8464",
        "emoji": ">>",
    },
    AlertType.TRADE_OPENED: {
        "subject_prefix": "Trade Opened",
        "color": "#27ae60",
        "emoji": ">>",
    },
    AlertType.TRADE_CLOSED: {
        "subject_prefix": "Trade Closed",
        "color": "#2980b9",
        "emoji": ">>",
    },
    AlertType.BUDGET_HIT: {
        "subject_prefix": "Budget Limit",
        "color": "#e67e22",
        "emoji": ">>",
    },
    AlertType.TOKEN_EXPIRY: {
        "subject_prefix": "Action Required",
        "color": "#c0392b",
        "emoji": ">>",
    },
    AlertType.BOT_ERROR: {
        "subject_prefix": "Bot Error",
        "color": "#c0392b",
        "emoji": ">>",
    },
    AlertType.BOT_STATUS: {
        "subject_prefix": "Bot Status",
        "color": "#7F8464",
        "emoji": ">>",
    },
}


def _get_et_time() -> str:
    """Get current Eastern Time as formatted string."""
    utc = datetime.now(timezone.utc)
    et_offset = timedelta(hours=-4)  # EDT
    et = utc + et_offset
    return et.strftime("%I:%M %p ET — %b %d, %Y")


def _build_html(alert_type: AlertType, title: str, body: str, details: dict = None) -> str:
    """Build a styled HTML email."""
    config = ALERT_CONFIG.get(alert_type, ALERT_CONFIG[AlertType.SIGNAL])
    color = config["color"]
    time_str = _get_et_time()

    details_html = ""
    if details:
        rows = ""
        for k, v in details.items():
            rows += f'<tr><td style="padding:4px 12px 4px 0;color:#8a847e;font-size:13px;">{k}</td><td style="padding:4px 0;font-size:13px;font-weight:500;">{v}</td></tr>'
        details_html = f'<table style="margin-top:12px;border-collapse:collapse;">{rows}</table>'

    return f"""
    <div style="font-family:'Inter',Arial,sans-serif;max-width:500px;margin:0 auto;background:#F5F3EE;padding:20px;">
      <div style="background:linear-gradient(165deg,#C4B99A 0%,#B8A88C 40%,#A89878 100%);padding:14px 20px;border-radius:10px 10px 0 0;">
        <span style="font-family:Georgia,serif;font-size:16px;color:#2E2E2C;">LumiSignals</span>
      </div>
      <div style="background:#FFFFFF;padding:20px;border-radius:0 0 10px 10px;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
        <div style="border-left:4px solid {color};padding-left:12px;margin-bottom:14px;">
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:{color};font-weight:600;margin-bottom:2px;">{config["subject_prefix"]}</div>
          <div style="font-size:16px;font-weight:500;color:#2E2E2C;">{title}</div>
        </div>
        <div style="font-size:13px;color:#2E2E2C;line-height:1.6;">{body}</div>
        {details_html}
        <div style="margin-top:16px;padding-top:12px;border-top:1px solid #eee;font-size:11px;color:#8a847e;">{time_str}</div>
      </div>
      <div style="text-align:center;margin-top:12px;font-size:10px;color:#8a847e;">
        LumiTrade — Financial publishing for educational purposes only
      </div>
    </div>
    """


def send_alert(
    alert_type: AlertType,
    title: str,
    body: str = "",
    details: dict = None,
    to_email: str = None,
    smtp_pass: str = None,
) -> bool:
    """Send an email alert.

    Args:
        alert_type: Type of alert (determines styling and subject prefix).
        title: Main headline (e.g. "BUY AAPL @ $270.50").
        body: Optional body text with more context.
        details: Optional dict of key-value pairs shown as a table.
        to_email: Recipient email. Defaults to SMTP_USER (send to self).
        smtp_pass: Gmail app password. Defaults to ALERT_EMAIL_PASSWORD env var.

    Returns:
        True if sent successfully.
    """
    password = smtp_pass or SMTP_PASS
    if not password:
        logger.warning("No email password configured — skipping alert")
        return False

    recipient = to_email or SMTP_USER
    config = ALERT_CONFIG.get(alert_type, ALERT_CONFIG[AlertType.SIGNAL])

    msg = MIMEMultipart("alternative")
    msg["From"] = f"LumiSignals <{SMTP_USER}>"
    msg["To"] = recipient
    msg["Subject"] = f"LumiSignals — {config['subject_prefix']}: {title}"

    # Plain text fallback
    plain = f"{config['subject_prefix']}: {title}\n\n{body}"
    if details:
        for k, v in details.items():
            plain += f"\n{k}: {v}"
    plain += f"\n\n{_get_et_time()}"

    html = _build_html(alert_type, title, body, details)

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, password)
            server.sendmail(SMTP_USER, recipient, msg.as_string())
        logger.info("Alert sent: %s — %s", config["subject_prefix"], title)
        return True
    except Exception as e:
        logger.error("Failed to send alert: %s", e)
        return False


# -----------------------------------------------------------------------
# Convenience functions for the bot runner
# -----------------------------------------------------------------------

def alert_signal(model: str, action: str, symbol: str, entry: float,
                 risk_reward: float, score: int = 0, **kwargs) -> bool:
    """Alert when a new signal fires."""
    title = f"{action} {symbol} @ {entry:.5f}"
    body = f"The {model.upper()} model detected a new trade setup."
    details = {
        "Model": model.upper(),
        "Action": action,
        "Symbol": symbol,
        "Entry": f"{entry:.5f}",
        "R:R": f"{risk_reward:.1f}",
    }
    if score:
        details["Score"] = f"{score}/100"
    if kwargs.get("stop"):
        details["Stop Loss"] = f"{kwargs['stop']:.5f}"
    if kwargs.get("target"):
        details["Take Profit"] = f"{kwargs['target']:.5f}"
    if kwargs.get("zone_type"):
        details["Zone"] = f"{kwargs.get('zone_timeframe', '')} {kwargs['zone_type']}"
    if kwargs.get("trigger_pattern"):
        details["Trigger"] = kwargs["trigger_pattern"]
    return send_alert(AlertType.SIGNAL, title, body, details, **{k: v for k, v in kwargs.items() if k in ("to_email", "smtp_pass")})


def alert_trade_opened(model: str, action: str, symbol: str, units: int,
                       entry: float, order_id: str, **kwargs) -> bool:
    """Alert when a trade is placed."""
    title = f"{action} {symbol} — {abs(units):,} units"
    body = f"Order {order_id} placed by the {model.upper()} model."
    details = {
        "Model": model.upper(),
        "Action": action,
        "Symbol": symbol,
        "Units": f"{abs(units):,}",
        "Entry": f"{entry:.5f}",
        "Order ID": order_id,
    }
    if kwargs.get("risk_amount"):
        details["Risk"] = f"${kwargs['risk_amount']:.2f}"
    return send_alert(AlertType.TRADE_OPENED, title, body, details, **{k: v for k, v in kwargs.items() if k in ("to_email", "smtp_pass")})


def alert_trade_closed(symbol: str, pl: float, pips: float, reason: str, **kwargs) -> bool:
    """Alert when a trade closes."""
    win = pl > 0
    title = f"{symbol} {'WIN' if win else 'LOSS'} — ${pl:+,.2f}"
    body = f"Trade closed by {reason}."
    details = {
        "Symbol": symbol,
        "P&L": f"${pl:+,.2f}",
        "Pips": f"{pips:+.1f}",
        "Reason": reason,
    }
    return send_alert(AlertType.TRADE_CLOSED, title, body, details, **{k: v for k, v in kwargs.items() if k in ("to_email", "smtp_pass")})


def alert_budget_hit(model: str, budget: float, spent: float, **kwargs) -> bool:
    """Alert when daily budget is exhausted."""
    title = f"{model.upper()} daily budget reached — ${budget:.0f}"
    body = f"The {model.upper()} model has used ${spent:.2f} of its ${budget:.0f} daily risk budget. No more trades will be placed today for this model."
    return send_alert(AlertType.BUDGET_HIT, title, body, **{k: v for k, v in kwargs.items() if k in ("to_email", "smtp_pass")})


def alert_token_expiry(service: str, days_left: int, **kwargs) -> bool:
    """Alert when an API token is about to expire."""
    title = f"{service} token expires in {days_left} day{'s' if days_left != 1 else ''}"
    body = f"Your {service} API token will expire soon. Please re-authorize to keep options analysis working."
    details = {"Service": service, "Days Left": str(days_left), "Action": "Run schwab_auth.py"}
    return send_alert(AlertType.TOKEN_EXPIRY, title, body, details, **{k: v for k, v in kwargs.items() if k in ("to_email", "smtp_pass")})


def alert_bot_error(error: str, **kwargs) -> bool:
    """Alert on bot errors."""
    title = "Bot encountered an error"
    return send_alert(AlertType.BOT_ERROR, title, error, **{k: v for k, v in kwargs.items() if k in ("to_email", "smtp_pass")})
