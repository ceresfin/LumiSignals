import os
import smtplib
from email.message import EmailMessage
from datetime import datetime

# Config
EMAIL_ADDRESS = "sonia.spirling@gmail.com"
EMAIL_PASSWORD = "aamswonhdgsbocgw"
TO_ADDRESS = "sonia.spirling@gmail.com"

LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../logs/sync.log"))

def send_log_email():
    msg = EmailMessage()
    msg['Subject'] = f"LumiTrade Sync Log – {datetime.now().strftime('%Y-%m-%d')}"
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = TO_ADDRESS
    msg.set_content("Attached is today's LumiTrade sync log file.")

    # Attach log file
    with open(LOG_FILE, "rb") as f:
        msg.add_attachment(f.read(), maintype="text", subtype="plain", filename="sync.log")

    # Send email
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        smtp.send_message(msg)

if __name__ == "__main__":
    send_log_email()
