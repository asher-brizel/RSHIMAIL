import imaplib
import email
from email.header import decode_header
import requests
import os
import cloudinary
import cloudinary.uploader

# הגדרות סביבה (נלקחות מה-GitHub Secrets)
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_PASS")
API_KEY = os.getenv("API_KEY")
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL")

# הגדרות API וג'ימייל
API_URL = "https://kehilnet.base44.app/api/entities/Announcement"
LABEL = "Rshimail" # ודא שהגדרת שם זהה בתווית בג'ימייל

# אתחול Cloudinary
if CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)

def clean_signature(text):
    """מנקה חתימות וקישורי מערכת מהמייל"""
    if not text:
        return ""
    
    # רשימת "סימני עצירה" - כל מה שמופיע מהם והלאה יימחק
    markers = [
        "רשימייל אנ\"ש - לוח המודעות",
        "ניתן להשיב לכתובת",
        "---",
        "-- ",
        "________________",
        "ניתן להצטרף לקבוצה",
        "Google Groups",
        "עקב אילוצי המערכת"
    ]
    
    for marker in markers:
        if marker in text:
            text = text.split(marker)[0]
            
    return text.strip()

def upload_to_cloud(file_data, file_name):
    """מעלה קובץ לענן ומחזיר לינק ישיר"""
    try:
        resource_type = "image" if file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')) else "raw"
        upload_result = cloudinary.uploader.upload(file_data, public_id=file_name, resource_type=resource_type)
        return upload_result.get("secure_url")
    except Exception as e:
        print(f"Error uploading {file_name}: {e}")
        return None

def sync():
    # התחברות לג'ימייל
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
    except Exception as e:
        print(f"Login failed: {e}")
        return

    # בחירת התווית
    status, _ = mail.select(LABEL)
    if status != 'OK':
        print(f"Label '{LABEL}' not found. Please check Gmail settings.")
        return

    # חיפוש כל המיילים בתווית
    _, search_data = mail.search(None, 'ALL')
    
    for num in search_data[0].split():
        _, data = mail.fetch(num, '(RFC822)')
        msg = email.message_from_bytes(data[0][1])
        
        # חילוץ נושא המייל
        subject, encoding = decode_header(msg["Subject"])[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding or "utf-8")
            
        content = ""
        image_url = ""
        file_url = ""
        file_name_attr = ""

        # מעבר על חלקי המייל
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # חילוץ וניקוי טקסט
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        raw_text = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        content = clean_signature(raw_text)
                    except:
                        continue
                
                # טיפול בקבצים מצורפים
                elif "attachment" in content_disposition:
                    f_name = part.get_filename()
                    if f_name:
                        # קידוד שם הקובץ במידה והוא בעברית
                        decoded_name, name_enc = decode_header(f_name)[0]
                        if isinstance(decoded_name, bytes):
                            f_name = decoded_name.decode(name_enc or "utf-8")
                            
                        f_data = part.get_payload(decode=True)
                        link = upload_to_cloud(f_data, f_name)
                        
                        if f_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                            image_url = link
                        else:
                            file_url = link
                            file_name_attr = f_name
        else:
            raw_text = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            content = clean_signature(raw_text)

        # שליחה ל-API של האתר
        payload = {
            "title": subject,
            "content": content if content else "הודעה ללא תוכן טקסטואלי",
            "priority": "רגילה",
            "image_url": image_url,
            "file_url": file_url,
            "file_name": file_name_attr
        }
        
        headers = {
            "api_key": API_KEY,
            "Content-Type": "application/json"
        }
        
        response = requests.post(API_URL, headers=headers, json=payload)
        
        if response.status_code in [200, 201]:
            print(f"Successfully synced: {subject}")
            # העברה לאשפה כדי שלא יסתנכרן שוב
            mail.store(num, '+FLAGS', '\\Deleted') 
        else:
            print(f"Failed to sync {subject}: {response.text}")

    mail.expunge()
    mail.logout()

if __name__ == "__main__":
    sync()
