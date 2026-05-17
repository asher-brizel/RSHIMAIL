import os
import re
import imaplib
import email
from email.header import decode_header
import requests
import mimetypes
import urllib.parse
from playwright.sync_api import sync_playwright

# הגדרות מה-GitHub Secrets
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_PASS")
API_KEY = os.getenv("API_KEY")
APP_ID = os.getenv("APP_ID")

BASE_DOMAIN = "kehilnet.base44.app"
UPLOAD_URL = f"https://{BASE_DOMAIN}/api/integrations/Core/UploadFile"
ANNOUNCEMENT_URL = f"https://{BASE_DOMAIN}/api/entities/Announcement"
PAYMENT_FORMS_URL = f"https://{BASE_DOMAIN}/api/entities/PaymentForms"

LABEL = "Rshimail"
NEDARIM_URL = "https://www.matara.pro/nedarimplus/online/?mosad=7004882"

# ==========================================
# קוד עזר ועיבוד טקסט (Gmail & Forms)
# ==========================================

def decode_mime_header(s):
    if not s: return ""
    try:
        parts = decode_header(s)
        decoded_parts = []
        for content, encoding in parts:
            if isinstance(content, bytes):
                decoded_parts.append(content.decode(encoding or 'utf-8', errors='ignore'))
            else:
                decoded_parts.append(content)
        return "".join(decoded_parts)
    except:
        return str(s)

def clean_title(title):
    cleaned = re.sub(r'^(\[.*?\]|\(.*?\))\s*', '', title)
    return cleaned.strip()

def clean_filename(filename):
    name = re.sub(r'[^\w\s.-]', '', filename)
    return name.strip() or "file"

def extract_drive_links(text):
    links = []
    drive_pattern = r'https://docs\.google\.com/[^\s<>"]+'
    found_urls = re.findall(drive_pattern, text)
    
    seen = set()
    for url in found_urls:
        if url not in seen:
            name = "קישור למסמך גוגל"
            if "document" in url: name = "מסמך Google Docs"
            elif "forms" in url: name = "טופס Google Forms"
            
            links.append({
                "url": url,
                "name": name,
                "type": "text/html"
            })
            seen.add(url)
    return links[:2]

def clean_signature(text):
    if not text: return ""
    markers = ["רשימייל אנ\"ש - לוח המודעות", "ניתן להשיב לכתובת", "---", "-- ", "________________", "Google Groups"]
    for marker in markers:
        if marker in text:
            text = text.split(marker)[0]
    return text.strip()

# ==========================================
# לוגיקת סנכרון Gmail -> Announcements
# ==========================================

def upload_file_to_base44(file_data, file_name):
    try:
        headers = {"api_key": API_KEY, "X-App-Id": APP_ID}
        safe_name = clean_filename(file_name)
        if '.' not in safe_name:
            ext = mimetypes.guess_extension(mimetypes.guess_type(file_name)[0] or "") or ".dat"
            safe_name += ext

        files = {'file': (safe_name, file_data)}
        response = requests.post(UPLOAD_URL, headers=headers, files=files)
        
        if response.status_code in [200, 201]:
            return response.json().get("file_url") or response.json().get("url")
        return None
    except Exception as e:
        print(f"DEBUG: Upload error: {e}")
        return None

def sync_gmail_announcements():
    print("--- Starting Gmail Sync ---")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
    except Exception as e:
        print(f"Gmail Login failed: {e}")
        return

    mail.select(LABEL)
    _, search_data = mail.search(None, 'ALL')
    email_ids = search_data[0].split()
    
    for num in email_ids:
        _, data = mail.fetch(num, '(RFC822)')
        msg = email.message_from_bytes(data[0][1])
        
        subject = clean_title(decode_mime_header(msg["Subject"]))
        print(f"Processing Email: {subject}")
        
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
                        attachments_list.extend(extract_drive_links(raw_text))
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
            attachments_list.extend(extract_drive_links(raw_text))
            content = clean_signature(raw_text)

        payload = {
            "title": subject,
            "content": content if content else "",
            "priority": "רגילה",
            "pinned": False,
            "image_url": primary_image,
            "attachments": attachments_list
        }

        headers = {"api_key": API_KEY, "X-App-Id": APP_ID, "Content-Type": "application/json"}
        response = requests.post(ANNOUNCEMENT_URL, headers=headers, json=payload)
        
        if response.status_code in [200, 201]:
            print(f"SUCCESS: {subject} synced with {len(attachments_list)} attachments.")
            mail.store(num, '+FLAGS', '\\Deleted')
        else:
            print(f"ERROR: Announcement status {response.status_code}")

    mail.expunge()
    mail.logout()
    print("Gmail Sync Finished.")

# ==========================================
# לוגיקת סנכרון Nedarim -> PaymentForms
# ==========================================

def get_existing_form_titles():
    headers = {"api_key": API_KEY, "Content-Type": "application/json"}
    try:
        response = requests.get(PAYMENT_FORMS_URL, headers=headers)
        if response.status_code == 200:
            return {r.get("title") for r in response.json() if r.get("title")}
    except Exception as e:
        print(f"DEBUG: Base44 fetch error: {e}")
    return set()

def insert_new_form(title, url, display_order):
    headers = {"api_key": API_KEY, "Content-Type": "application/json"}
    payload = {
        "title": title,
        "url": url,
        "display_order": display_order
    }
    try:
        res = requests.post(PAYMENT_FORMS_URL, headers=headers, json=payload)
        if res.status_code in [200, 201]:
            print(f"[SUCCESS] Added Form: {title}")
        else:
            print(f"[FAILED] Form {title} status: {res.status_code}")
    except Exception as e:
        print(f"DEBUG: Form insert error: {e}")

def sync_nedarim_forms():
    print("--- Starting Nedarim Forms Sync ---")
    existing_titles = get_existing_form_titles()
    print(f"Found {len(existing_titles)} existing forms in Base44.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(NEDARIM_URL)
        
        try:
            page.wait_for_selector("#GroupeMainBt", timeout=15000)
            page.wait_for_timeout(2000)
            
            raw_items = page.evaluate("""() => {
                const data = [];
                const rows = document.querySelectorAll('#GroupeMainBt .GroupeDivCss');
                rows.forEach((row, index) => {
                    const btn = row.querySelector('.GroupeBtCss') || row.querySelector('input[type="button"]');
                    if (btn) {
                        data.push({
                            title: (btn.value || btn.innerText || "").trim(),
                            fullText: (row.innerText || "").trim(),
                            order: index + 1
                        });
                    }
                });
                return data;
            }""")
        except Exception as e:
            print(f"Playwright Scrape Failed: {e}")
            raw_items = []
        browser.close()

    for item in raw_items:
        title = item["title"]
        full_text = item["fullText"]
        order = item["order"]
        
        if title in existing_titles:
            continue
            
        amount_match = re.search(r'(?:₪|ש"ח)\s*([\d,]+)', full_text) or re.search(r'([\d,]+)\s*(?:₪|ש"ח)', full_text)
        amount = amount_match.group(1).replace(",", "") if amount_match else None
        
        encoded_groupe = urllib.parse.quote(title)
        final_url = f"https://www.matara.pro/nedarimplus/online/?mosad=7004882&groupe={encoded_groupe}"
        if amount:
            final_url += f"&amount={amount}"
            
        print(f"[NEW FORM] Detected: {title}")
        insert_new_form(title, final_url, order)
    print("Nedarim Sync Finished.")

# ==========================================
# Orchestrator
# ==========================================

if __name__ == "__main__":
    sync_gmail_announcements()
    sync_nedarim_forms()
    print("All sync operations completed successfully.")
