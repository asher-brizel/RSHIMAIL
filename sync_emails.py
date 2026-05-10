import imaplib
import email
from email.header import decode_header
import requests
import os
import mimetypes
import re

# הגדרות סביבה (נלקחות מה-GitHub Secrets)
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_PASS")
API_KEY = os.getenv("API_KEY")
APP_ID = os.getenv("APP_ID")

# כתובות ה-API של בייס44
UPLOAD_URL = "https://api.base44.com/api/integrations/Core/UploadFile"
ANNOUNCEMENT_URL = f"https://api.base44.com/api/apps/{APP_ID}/entities/Announcement"

LABEL = "Rshimail" # שם התווית באנגלית בג'ימייל

def decode_mime_header(s):
    """פענוח עברית בכותרות ושמות קבצים"""
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
    """מסיר את שם השולח בסוגריים מהכותרת, למשל [רשימייל אנ\"ש]"""
    cleaned = re.sub(r'^\[.*?\]\s*', '', title)
    return cleaned.strip()

def clean_signature(text):
    """מסיר חתימות וקישורי מערכת מיותרים מגוף המייל"""
    if not text: return ""
    markers = [
        "רשימייל אנ\"ש - לוח המודעות",
        "ניתן להשיב לכתובת",
        "---",
        "-- ",
        "________________",
        "ניתן להצטרף לקבוצה",
        "Google Groups"
    ]
    for marker in markers:
        if marker in text:
            text = text.split(marker)[0]
    return text.strip()

def upload_file_to_base44(file_data, file_name):
    """מעלה קובץ גולמי ומחזיר את ה-URL שלו מהשרת"""
    try:
        headers = {"Authorization": f"Bearer {API_KEY}"}
        files = {'file': (file_name, file_data)}
        response = requests.post(UPLOAD_URL, headers=headers, files=files)
        
        if response.status_code in [200, 201]:
            return response.json().get("file_url")
        else:
            print(f"DEBUG: Upload failed for {file_name}. Status: {response.status_code}")
            return None
    except Exception as e:
        print(f"DEBUG: Upload error: {e}")
        return None

def sync():
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
    except Exception as e:
        print(f"Login failed: {e}")
        return

    # בחירת התווית
    status, _ = mail.select(LABEL)
    if status != 'OK':
        print(f"Label '{LABEL}' not found.")
        return

    _, search_data = mail.search(None, 'ALL')
    
    for num in search_data[0].split():
        _, data = mail.fetch(num, '(RFC822)')
        msg = email.message_from_bytes(data[0][1])
        
        # כותרת נקייה
        raw_subject = decode_mime_header(msg["Subject"])
        subject = clean_title(raw_subject)
        
        content = ""
        attachments_list = []
        primary_image = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # טקסט
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        raw_text = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        content = clean_signature(raw_text)
                    except: continue
                
                # קבצים
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
                            
                            # שמירת התמונה הראשונה לצורך תצוגה מקדימה
                            if f_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')) and not primary_image:
                                primary_image = file_url
        else:
            raw_text = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            content = clean_signature(raw_text)

        # בניית ה-Payload הסופי
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
        
        response = requests.post(ANNOUNCEMENT_URL, headers=headers, json=payload)
        
        if response.status_code in [200, 201]:
            print(f"SUCCESS: {subject} synced.")
            # סימון למחיקה מהתווית בג'ימייל
            mail.store(num, '+FLAGS', '\\Deleted')
        else:
            print(f"ERROR: Sync failed for {subject}. Status: {response.status_code}")

    mail.expunge()
    mail.logout()

if __name__ == "__main__":
    sync()
