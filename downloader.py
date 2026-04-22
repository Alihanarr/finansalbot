import os
import requests
import json
import pdfplumber
import google.generativeai as genai
from playwright.sync_api import sync_playwright
from datetime import datetime

# Yapılandırmalar
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def get_ai_analysis(current_pdf_text, previous_summary, report_type):
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"""
    Sen üst düzey bir finansal analistsin. Bir İşletme Mühendisi için aşağıdaki {report_type} raporunu analiz et.
    FORMAT: 1.MANŞET, 2.KÜRESEL, 3.TEKNİK, 4.📈/📉 HİSSE HABERLERİ, 5.TREND & KIYASLAMA.
    KIYASLAMA VERİSİ: {previous_summary if previous_summary else "İlk rapor."}
    METİN: {current_pdf_text[:12000]}
    """
    response = model.generate_content(prompt)
    return response.text

def process_automation():
    targets = {"günlük piyasa özeti": "SABAH_RAPORU", "gün ortası notları": "OGLE_RAPORU"}
    
    # TARİH FORMATLARI
    bugun_sayi = datetime.now().strftime("%d.%m.%Y") # 22.04.2026
    bugun_gun = datetime.now().strftime("%d ") # 22 
    aylar = {"01":"Ocak","02":"Şubat","03":"Mart","04":"Nisan","05":"Mayıs","06":"Haziran",
             "07":"Temmuz","08":"Ağustos","09":"Eylül","10":"Ekim","11":"Kasım","12":"Aralık"}
    ay_ismi = aylar[datetime.now().strftime("%m")] # Nisan
    bugun_metin = f"{bugun_gun}{ay_ismi}".lower() # 22 nisan
    
    history_file = "history.json"
    history = json.load(open(history_file)) if os.path.exists(history_file) else {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.garantibbvayatirim.com.tr/arastirma-raporlari", wait_until="networkidle")
        items = page.query_selector_all(".reports-list-item")
        
        print(f"--- Arama Başlatıldı: {bugun_sayi} / {bugun_metin} ---")

        for target_title, report_key in targets.items():
            found = False
            for item in items:
                text = item.inner_text().lower()
                if target_title in text and (bugun_sayi in text or bugun_metin in text):
                    filename = f"{report_key}_{bugun_sayi}.pdf"
                    if history.get(f"{report_key}_LAST_DATE") != bugun_sayi:
                        print(f"BULDUM: {target_title}")
                        url = item.query_selector("a.report-download").get_attribute("href")
                        if not url.startswith("http"): url = "https://www.garantibbvayatirim.com.tr" + url
                        
                        resp = requests.get(url)
                        with open(filename, "wb") as f: f.write(resp.content)
                        
                        with pdfplumber.open(filename) as pdf:
                            raw_text = "".join(p.extract_text() for p in pdf.pages[:4])
                        
                        analysis = get_ai_analysis(raw_text, history.get(f"{report_key}_SUMMARY", ""), target_title)
                        send_telegram(analysis)
                        
                        history[f"{report_key}_LAST_DATE"] = bugun_sayi
                        history[f"{report_key}_SUMMARY"] = analysis
                        found = True
                        break
            if not found: print(f"HENÜZ YOK: {target_title}")
        
        with open(history_file, "w") as f: json.dump(history, f)
        browser.close()

if __name__ == "__main__":
    process_automation()
