import imaplib
import email
from email.header import decode_header
import requests
import os
import cloudinary
import cloudinary.uploader

# הגדרות סביבה
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_PASS")
API_KEY = os.getenv("API_KEY")
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL") # פורמט: cloudinary://key:secret@name

API_URL = "https://kehilnet.base44.app/api/entities/Announcement"
LABEL = "Rshimail"

# אתחול Cloudinary
cloudinary.config(cloudinary_url=CLOUDINARY_URL)

def upload_to_cloud(file_data, file_name):
    """מעלה קובץ לענן ומחזיר לינק ישיר"""
    try:
        # זיהוי אם זה תמונה או קובץ כללי
        resource_type = "image" if file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')) else "raw"
        upload_result = cloudinary.uploader.upload(file_data, public_id=file_name, resource_type=resource_type)
        return upload_result.get("secure_url")
    except Exception as e:
        print(f"Error uploading {file_name}: {e}")
        return None

def sync():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_USER, GMAIL_PASS)
    
    status, _ = mail.select(f'"{LABEL}"')
    if status != 'OK': return

    _, search_data = mail.search(None, 'ALL')
    
    for num in search_data[0].split():
        _, data = mail.fetch(num, '(RFC822)')
        msg = email.message_from_bytes(data[0][1])
        
        subject, encoding = decode_header(msg["Subject"])[0]
        if isinstance(subject, bytes): subject = subject.decode(encoding or "utf-8")
            
        content = ""
        image_url = ""
        file_url = ""
        file_name_attr = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # חילוץ טקסט
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    content = part.get_payload(decode=True).decode()
                
                # חילוץ קבצים מצורפים
                elif "attachment" in content_disposition:
                    f_name = part.get_filename()
                    if f_name:
                        f_data = part.get_payload(decode=True)
                        link = upload_to_cloud(f_data, f_name)
                        
                        # מיון ל-image_url או file_url לפי הסוג
                        if f_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                            image_url = link
                        else:
                            file_url = link
                            file_name_attr = f_name
        else:
            content = msg.get_payload(decode=True).decode()

        # בניית ה-Payload ל-API לפי הסכימה שלך
        payload = {
            "title": subject,
            "content": content or "ללא תוכן",
            "priority": "רגילה",
            "image_url": image_url,
            "file_url": file_url,
            "file_name": file_name_attr
        }
        
        headers = {"api_key": API_KEY, "Content-Type": "application/json"}
        response = requests.post(API_URL, headers=headers, json=payload)
        
        if response.status_code in [200, 201]:
            print(f"Success: {subject}")
            mail.store(num, '+FLAGS', '\\Deleted') # מחיקה לאחר סנכרון

    mail.expunge()
    mail.logout()

if __name__ == "__main__":
    sync()
