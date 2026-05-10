import imaplib
import email
from email.header import decode_header
import requests
import os

# הגדרות סביבה
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_PASS")
API_KEY = os.getenv("API_KEY")

# כתובות ה-API של בייס44
BASE_URL = "https://kehilnet.base44.app/api"
ANNOUNCEMENT_URL = f"{BASE_URL}/entities/Announcement"
UPLOAD_URL = f"{BASE_URL}/upload" # ודא שזו הכתובת הנכונה להעלאת קבצים

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

def clean_signature(text):
    if not text: return ""
    markers = ["רשימייל אנ\"ש - לוח המודעות", "ניתן להשיב לכתובת", "---", "-- ", "________________", "Google Groups"]
    for marker in markers:
        if marker in text:
            text = text.split(marker)[0]
    return text.strip()

def upload_file_to_base44(file_data, file_name):
    """מעלה קובץ ישירות לבייס44 ומחזיר את ה-URL שלו"""
    try:
        headers = {"api_key": API_KEY}
        files = {'file': (file_name, file_data)}
        response = requests.post(UPLOAD_URL, headers=headers, files=files)
        
        if response.status_code in [200, 201]:
            # בדרך כלל ה-API מחזיר אובייקט עם שדה url
            return response.json().get("url")
        else:
            print(f"Failed to upload {file_name}: {response.text}")
            return None
    except Exception as e:
        print(f"Upload error: {e}")
        return None

def sync():
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
    except Exception as e:
        print(f"Login error: {e}")
        return

    mail.select(LABEL)
    _, search_data = mail.search(None, 'ALL')
    
    for num in search_data[0].split():
        _, data = mail.fetch(num, '(RFC822)')
        msg = email.message_from_bytes(data[0][1])
        
        subject = decode_mime_header(msg["Subject"])
        content = ""
        attachments_list = []
        primary_image = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # טיפול בטקסט
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    raw_text = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    content = clean_signature(raw_text)
                
                # טיפול בקבצים (תמונות ומסמכים)
                elif "attachment" in content_disposition or part.get_filename():
                    f_name_raw = part.get_filename()
                    if f_name_raw:
                        f_name = decode_mime_header(f_name_raw)
                        f_data = part.get_payload(decode=True)
                        
                        file_url = upload_file_to_base44(f_data, f_name)
                        
                        if file_url:
                            # הוספה למערך הקבצים החדש
                            attachments_list.append({
                                "url": file_url,
                                "name": f_name
                            })
                            # אם זו תמונה, נשמור אותה גם לשדה הראשי
                            if f_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')) and not primary_image:
                                primary_image = file_url
        else:
            content = clean_signature(msg.get_payload(decode=True).decode('utf-8', errors='ignore'))

        # בניית האובייקט לפי הסכימה החדשה
        payload = {
            "title": subject,
            "content": content if content else "",
            "priority": "רגילה",
            "image_url": primary_image,
            "attachments": attachments_list # המערך החדש
        }
        
        # תמיכה בשדות ישנים ליתר ביטחון
        if attachments_list:
            payload["file_url"] = attachments_list[0]["url"]
            payload["file_name"] = attachments_list[0]["name"]

        headers = {"api_key": API_KEY, "Content-Type": "application/json"}
        res = requests.post(ANNOUNCEMENT_URL, headers=headers, json=payload)
        
        if res.status_code in [200, 201]:
            print(f"Synced: {subject}")
            mail.store(num, '+FLAGS', '\\Deleted')

    mail.expunge()
    mail.logout()

if __name__ == "__main__":
    sync()
