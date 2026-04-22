import os
import requests
import json
import pdfplumber
import google.generativeai as genai
from playwright.sync_api import sync_playwright
from datetime import datetime
import time

# ==========================================
# GÜVENLİ YAPILANDIRMA
# ==========================================
def clean_env(key):
    val = os.environ.get(key, "")
    return str(val).strip().replace("[", "").replace("]", "").replace("'", "").replace('"', "")

genai.configure(api_key=clean_env("GEMINI_API_KEY"))
TELEGRAM_TOKEN = clean_env("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = clean_env("TELEGRAM_CHAT_ID")

def send_telegram(message):
    """Mesajı parçalara bölerek Telegram'a gönderir."""
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    limit = 4000
    parts = [message[i:i+limit] for i in range(0, len(message), limit)]
    
    for part in parts:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": part, "parse_mode": "Markdown"}
        try:
            resp = requests.post(api_url, json=payload, timeout=30)
            if resp.status_code != 200:
                requests.post(api_url, json={"chat_id": TELEGRAM_CHAT_ID, "text": part}, timeout=30)
        except Exception as e:
            print(f"!!! Telegram Hatası: {e}")
        time.sleep(1)

def get_ai_analysis(current_pdf_text, previous_summary, report_type):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        header_title = report_type.upper() + " ANALİZİ"
        prompt = f"""
        Sen kıdemli bir finansal analistsin. Bir İşletme Mühendisi için profesyonel analiz yap.
        BAŞLIK: **{header_title}**
        TARİH: _{datetime.now().strftime("%d.%m.%Y")} tarihli rapor özeti_
        KURALLAR: Giriş cümlesi kullanma. Tabloları ``` içine al. En sona kıyaslama ekle.
        KIYASLANACAK ÖZET: {previous_summary if previous_summary else "İlk veri."}
        METİN: {current_pdf_text[:12000]}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"ERROR_CODE_GEMINI: {str(e)}"

def process_automation():
    targets = {"günlük piyasa özeti": "SABAH_RAPORU", "gün ortası notları": "OGLE_RAPORU"}
    bugun_sayi = datetime.now().strftime("%d.%m.%Y")
    
    aylar = {"01":"Ocak","02":"Şubat","03":"Mart","04":"Nisan","05":"Mayıs","06":"Haziran",
             "07":"Temmuz","08":"Ağustos","09":"Eylül","10":"Ekim","11":"Kasım","12":"Aralık"}
    bugun_metin = f"{datetime.now().strftime('%d')} {aylar[datetime.now().strftime('%m')]}".lower()

    history_file = "history.json"
    history = json.load(open(history_file)) if os.path.exists(history_file) else {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # PARANTEZSİZ VE TEMİZ USER AGENT TANIMI
        page = browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
        
        # URL TEK VE TIRNAK İÇİNDE
        target_url = "[https://www.garantibbvayatirim.com.tr/arastirma-raporlari](https://www.garantibbvayatirim.com.tr/arastirma-raporlari)"
        print(f"--- Siteye Gidiliyor: {target_url} ---")
        
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(10000)
            
            items = page.query_selector_all(".reports-list-item")
            print(f"Sitede {len(items)} adet rapor bulundu.")

            for target_title, report_key in targets.items():
                for item in items:
                    text = item.inner_text().lower()
                    if target_title in text and (bugun_sayi in text or bugun_metin in text):
                        if history.get(f"{report_key}_LAST_DATE") != bugun_sayi:
                            print(f"--- {target_title} İşleniyor... ---")
                            link = item.query_selector("a.report-download")
                            if link:
                                pdf_url = link.get_attribute("href")
                                if not pdf_url.startswith("http"): pdf_url = "[https://www.garantibbvayatirim.com.tr](https://www.garantibbvayatirim.com.tr)" + pdf_url
                                
                                resp = requests.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
                                with open("temp.pdf", "wb") as f: f.write(resp.content)
                                
                                with pdfplumber.open("temp.pdf") as pdf:
                                    raw_text = "".join(p.extract_text() for p in pdf.pages[:4])
                                
                                time.sleep(2)
                                analysis = get_ai_analysis(raw_text, history.get(f"{report_key}_SUMMARY", ""), target_title)
                                
                                if "ERROR" not in analysis and "429" not in analysis:
                                    send_telegram(analysis)
                                    history[f"{report_key}_LAST_DATE"] = bugun_sayi
                                    history[f"{report_key}_SUMMARY"] = analysis
                                    print(f"--- {target_title} TAMAMLANDI ---")
                                break
        except Exception as e:
            print(f"HATA: {e}")
        finally:
            with open(history_file, "w") as f:
                json.dump(history, f)
            browser.close()

if __name__ == "__main__":
    process_automation()
