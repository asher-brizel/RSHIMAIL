import imaplib
import email
from email.header import decode_header
import requests
import os
import mimetypes
import re

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_PASS")
API_KEY = os.getenv("API_KEY")
APP_ID = os.getenv("APP_ID")

UPLOAD_URL = "https://api.base44.com/api/integrations/Core/UploadFile"
ANNOUNCEMENT_URL = f"https://api.base44.com/api/apps/{APP_ID}/entities/Announcement"

LABEL = "Rshimail"

def decode_mime_header(s):
    if not s: return ""
    parts = decode_header(s)
    decoded_parts = []
    for content, encoding in parts:
        if isinstance(content, bytes):
            decoded_parts.append(content.decode(encoding or 'utf-8', errors='ignore'))
        else:
            decoded_parts.append(content)
    return "".join(decoded_parts)

def clean_title(title):
    cleaned = re.sub(r'^\[.*?\]\s*', '', title)
    return cleaned.strip()

def clean_signature(text):
    if not text: return ""
    markers = ["רשימייל אנ\"ש - לוח המודעות", "ניתן להשיב לכתובת", "---", "-- ", "________________", "Google Groups"]
    for marker in markers:
        if marker in text:
            text = text.split(marker)[0]
    return text.strip()

def upload_file_to_base44(file_data, file_name):
    try:
        headers = {"Authorization": f"Bearer {API_KEY}"}
        files = {'file': (file_name, file_data)}
        response = requests.post(UPLOAD_URL, headers=headers, files=files)
        
        if response.status_code in [200, 201]:
            url = response.json().get("file_url")
            print(f"-> File uploaded: {file_name} -> {url}")
            return url
        else:
            print(f"-> Upload FAILED for {file_name}: {response.text}")
            return None
    except Exception as e:
        print(f"-> Upload Exception: {e}")
        return None

def sync():
    print(f"Connecting to Gmail as {GMAIL_USER}...")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
        print("Gmail Login Successful.")
    except Exception as e:
        print(f"Gmail Login failed: {e}")
        return

    status, _ = mail.select(LABEL)
    if status != 'OK':
        print(f"CRITICAL: Label '{LABEL}' not found in Gmail! Make sure you renamed the label to Rshimail.")
        return

    _, search_data = mail.search(None, 'ALL')
    email_ids = search_data[0].split()
    print(f"Found {len(email_ids)} emails in label '{LABEL}'.")
    
    for num in email_ids:
        print(f"Processing email ID: {num.decode()}...")
        _, data = mail.fetch(num, '(RFC822)')
        msg = email.message_from_bytes(data[0][1])
        
        raw_subject = decode_mime_header(msg["Subject"])
        subject = clean_title(raw_subject)
        print(f"Subject: {subject}")
        
        content = ""
        attachments_list = []
        primary_image = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        raw_text = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        content = clean_signature(raw_text)
                    except: continue
                
                elif "attachment" in content_disposition or part.get_filename():
                    f_name_raw = part.get_filename()
                    if f_name_raw:
                        f_name = decode_mime_header(f_name_raw)
                        f_data = part.get_payload(decode=True)
                        file_url = upload_file_to_base44(f_data, f_name)
                        
                        if file_url:
                            mime_type, _ = mimetypes.guess_type(f_name)
                            attachments_list.append({
                                "url": file_url,
                                "name": f_name,
                                "type": mime_type or "application/octet-stream"
                            })
                            if f_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')) and not primary_image:
                                primary_image = file_url
        else:
            raw_text = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            content = clean_signature(raw_text)

        payload = {
            "title": subject,
            "content": content if content else "",
            "priority": "רגילה",
            "pinned": False,
            "image_url": primary_image,
            "attachments": attachments_list
        }

        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        
        print(f"Sending Announcement to Base44...")
        response = requests.post(ANNOUNCEMENT_URL, headers=headers, json=payload)
        
        if response.status_code in [200, 201]:
            print(f"SUCCESS: Announcement created. Server returned: {response.text}")
            mail.store(num, '+FLAGS', '\\Deleted')
        else:
            print(f"ERROR: Base44 rejected the announcement. Status: {response.status_code}, Body: {response.text}")

    mail.expunge()
    mail.logout()
    print("Done.")

if __name__ == "__main__":
    sync()
