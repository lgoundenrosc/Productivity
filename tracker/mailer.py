"""Sends the digest through Gmail SMTP with an app password."""
import os
import smtplib
from email.message import EmailMessage


def send(subject, html_body):
    sender = os.environ["GMAIL_ADDRESS"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = os.environ.get("DIGEST_TO", sender)
    msg.set_content("This digest is HTML. Open it in an email client that shows HTML.")
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(sender, os.environ["GMAIL_APP_PASSWORD"])
        s.send_message(msg)
