import smtplib
from datetime import date
from email.message import EmailMessage
import os
from dotenv import load_dotenv

load_dotenv()


def send_mail_with_excel(recipient_email):
    subject = "Hafele Guncel Stoklar"
    content = r"Guncel stoklari iceren .xlsx dosyasini ekte bulabilirsiniz."

    sender_email = os.getenv("gmail_sender_email")
    app_password = os.getenv("gmail_app_password")
    excel_file = "excel_file_to_mail.xlsx"

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = recipient_email
    msg.set_content(content)

    # create today's date for the product_info_table
    today_s_date = str(date.today()).replace('-', '_')
    filename_to_be_sent = f'{today_s_date} Hafele Güncel Stoklar.xlsx'

    with open(excel_file, 'rb') as f:
        file_data = f.read()
    msg.add_attachment(file_data, maintype="application", subtype="xlsx", filename=filename_to_be_sent)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(sender_email, app_password)
        smtp.send_message(msg)
        print("Done!")


if __name__ == "__main__":
    send_mail_with_excel("ercan@evan.com.tr")