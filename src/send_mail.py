"""
src/send_mail.py
Migrated from scrape_all_products_main branch.
Email utilities for sending plain-text alerts and Excel attachments.
"""
import smtplib
from datetime import date
from email.message import EmailMessage
import os
from dotenv import load_dotenv

load_dotenv()


def send_mail(recipient_email, subject, body):
    """Send a plain-text email notification."""
    sender_email = os.getenv("gmail_sender_email")
    app_password = os.getenv("gmail_app_password")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender_email, app_password)
        smtp.send_message(msg)
        print(f"✅ Email sent to {recipient_email} | Subject: {subject}")


def send_mail_with_excel(recipient_email, excel_file):
    """Send the generated Excel report as an attachment."""
    subject = "Hafele Guncel Stoklar"
    content = r"Guncel stoklari iceren .xlsx dosyasini ekte bulabilirsiniz."

    sender_email = os.getenv("gmail_sender_email")
    app_password = os.getenv("gmail_app_password")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg.set_content(content)

    today_s_date = str(date.today()).replace("-", "_")
    filename_to_be_sent = f"{today_s_date} Hafele Güncel Stoklar.xlsx"

    with open(excel_file, "rb") as f:
        file_data = f.read()
    msg.add_attachment(
        file_data, maintype="application", subtype="xlsx", filename=filename_to_be_sent
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender_email, app_password)
        smtp.send_message(msg)
        print(f"✅ Excel email sent to {recipient_email}")
