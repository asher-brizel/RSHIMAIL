import imaplib
import email
from email.header import decode_header
import requests
import os
import mimetypes
import re

# הגדרות מה-GitHub Secrets
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_PASS")
API_KEY = os.getenv("API_KEY")
APP_ID = os.getenv("APP_ID")

BASE_DOMAIN = "kehilnet.base44.app"
UPLOAD_URL = f"https://{BASE_DOMAIN}/api/integrations/Core/UploadFile"
ANNOUNCEMENT_URL = f"https://{BASE_DOMAIN}/api/entities/Announcement"

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
    cleaned = re.sub(r'^(\[.*?\]|\(.*?\))\s*', '', title)
    return cleaned.strip()

def clean_filename(filename):
    """מנקה את שם הקובץ לתווים לטיניים כדי למנוע שגיאה 400 בשרת"""
    name = re.sub(r'[^\w\s.-]', '', filename)
    if not name.strip():
        return "attachment"
    return name.strip()

def clean_signature(text):
    if not text: return ""
    markers = ["רשימייל אנ\"ש - לוח המודעות", "ניתן להשיב לכתובת", "---", "-- ", "________________", "Google Groups"]
    for marker in markers:
        if marker in text:
            text = text.split(marker)[0]
    return text.strip()

def upload_file_to_base44(file_data, file_name):
    try:
        # כאן הוספתי את ה-X-App-Id שהיה חסר ב-Logs
        headers = {
            "api_key": API_KEY,
            "X-App-Id": APP_ID
        }
        
        # יצירת שם קובץ בטוח להעלאה הטכנית
        safe_name = clean_filename(file_name)
        # וודוא שיש סיומת קובץ
        if '.' not in safe_name:
            ext = mimetypes.guess_extension(mimetypes.guess_type(file_name)[0] or "") or ".dat"
            safe_name += ext

        files = {'file': (safe_name, file_data)}
        response = requests.post(UPLOAD_URL, headers=headers, files=files)
        
        if response.status_code in [200, 201]:
            data = response.json()
            # מחלץ את הלינק - מנסה כמה שמות שדות נפוצים
            return data.get("file_url") or data.get("url") or data.get("path")
        else:
            print(f"-> Upload FAILED for {file_name}. Status: {response.status_code}, Body: {response.text}")
            return None
    except Exception as e:
        print(f"-> Upload Exception for {file_name}: {e}")
        return None

def sync():
    print(f"Connecting to Gmail...")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
    except Exception as e:
        print(f"Gmail Login failed: {e}")
        return

    mail.select(LABEL)
    _, search_data = mail.search(None, 'ALL')
    email_ids = search_data[0].split()
    print(f"Found {len(email_ids)} emails.")
    
    for num in email_ids:
        _, data = mail.fetch(num, '(RFC822)')
        msg = email.message_from_bytes(data[0][1])
        
        raw_subject = decode_mime_header(msg["Subject"])
        subject = clean_title(raw_subject)
        print(f"Processing: {subject}")
        
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
                                "name": f_name, # שם המקור בעברית נשמר כאן
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
            "api_key": API_KEY,
            "X-App-Id": APP_ID,
            "Content-Type": "application/json"
        }
        
        response = requests.post(ANNOUNCEMENT_URL, headers=headers, json=payload)
        
        if response.status_code in [200, 201]:
            print(f"SUCCESS: Announcement created.")
            mail.store(num, '+FLAGS', '\\Deleted')
        else:
            print(f"ERROR: Sync failed. Status: {response.status_code}, Body: {response.text}")

    mail.expunge()
    mail.logout()
    print("Done.")

if __name__ == "__main__":
    sync()
