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
    Sen üst düzey bir finansal analistsin. Bir İşletme Mühendisi ve SPL Düzey 1 sahibi bir profesyonel için aşağıdaki {report_type} raporunu analiz et.
    
    FORMAT ŞARTLARI:
    1. MANŞET: En kritik gelişmeyi vurgulayan iddialı bir başlık ve 2 cümlelik özet.
    2. KÜRESEL & MAKRO: Jeopolitik riskler, faiz beklentileri ve emtia yorumları.
    3. TEKNİK SEVİYELER: BIST100 ve VİOP için destek/direnç noktaları.
    4. ÖNEMLİ HİSSE HABERLERİ: Rapordaki (+), (-) ve (=) işaretli haberleri filtrele. Yanlarına 📈 (+) veya 📉 (-) koy ve 'Yükseliş/Düşüş Bekleniyor' notu ekle.
    5. TREND & KIYASLAMA: Aşağıdaki 'Önceki Rapor Özeti' ile karşılaştırarak; teknik seviye, haber akışı veya sinyal değişimlerini belirt.

    ÖNCEKİ RAPOR ÖZETİ (KIYASLAMA İÇİN):
    {previous_summary if previous_summary else "İlk rapor, kıyaslama verisi yok."}

    GÜNCEL RAPOR METNİ:
    {current_pdf_text[:12000]}
    """
    
    response = model.generate_content(prompt)
    return response.text

def process_automation():
    targets = {
        "günlük piyasa özeti": "SABAH_RAPORU",
        "gün ortası notları": "OGLE_RAPORU"
    }
    bugun = datetime.now().strftime("%d.%m.%Y")
    history_file = "history.json"
    
    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            history = json.load(f)
    else:
        history = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.garantibbvayatirim.com.tr/arastirma-raporlari", wait_until="networkidle")
        items = page.query_selector_all(".reports-list-item")
        
        for target_title, report_key in targets.items():
            for item in items:
                item_text = item.inner_text().lower()
                if target_title in item_text and bugun in item_text:
                    filename = f"{report_key}_{bugun}.pdf"
                    
                    if history.get(f"{report_key}_LAST_DATE") != bugun:
                        report_url = item.query_selector("a.report-download").get_attribute("href")
                        if not report_url.startswith("http"):
                            report_url = "https://www.garantibbvayatirim.com.tr" + report_url
                        
                        resp = requests.get(report_url)
                        with open(filename, "wb") as f:
                            f.write(resp.content)
                        
                        with pdfplumber.open(filename) as pdf:
                            current_text = "".join(page.extract_text() for page in pdf.pages[:4])
                        
                        prev_summary = history.get(f"{report_key}_SUMMARY", "")
                        analysis = get_ai_analysis(current_text, prev_summary, target_title)
                        
                        send_telegram(analysis)
                        
                        history[f"{report_key}_LAST_DATE"] = bugun
                        history[f"{report_key}_SUMMARY"] = analysis
                        
                        with open(history_file, "w") as f:
                            json.dump(history, f)
                        break
        browser.close()

if __name__ == "__main__":
    process_automation()
