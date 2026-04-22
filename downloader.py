import os
import requests
import json
import pdfplumber
import google.generativeai as genai
from playwright.sync_api import sync_playwright
from datetime import datetime
import time

# ==========================================
# GÜVENLİ YAPILANDIRMA (TEMİZLEME)
# ==========================================
def clean_env(key):
    val = os.environ.get(key, "")
    # Parantez, tırnak ve boşlukları temizle
    return val.strip().replace("[", "").replace("]", "").replace("'", "").replace('"', "")

genai.configure(api_key=clean_env("GEMINI_API_KEY"))
TELEGRAM_TOKEN = clean_env("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = clean_env("TELEGRAM_CHAT_ID")

def send_telegram(message):
    """URL'yi en saf haliyle kurar ve mesajı gönderir."""
    # Adresin başında veya sonunda hiçbir yabancı karakter kalmadığından emin oluyoruz
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    print(f"DEBUG: Telegram URL Hazırlandı (Güvenlik için gizli tutuluyor)")
    
    limit = 4000
    parts = [message[i:i+limit] for i in range(0, len(message), limit)]
    
    for part in parts:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID, 
            "text": part, 
            "parse_mode": "Markdown"
        }
        try:
            # URL'nin string olduğundan emin olarak gönderiyoruz
            resp = requests.post(str(url), json=payload, timeout=30)
            if resp.status_code != 200:
                # Markdown hatası ihtimaline karşı düz metin dene
                requests.post(str(url), json={"chat_id": TELEGRAM_CHAT_ID, "text": part}, timeout=30)
            print(f"DEBUG: Telegram Sunucu Yanıtı: {resp.status_code}")
        except Exception as e:
            print(f"!!! Telegram Gönderim Hatası: {e}")
        time.sleep(2)

def get_ai_analysis(current_pdf_text, previous_summary, report_type):
    try:
        # En kararlı modele zorla
        model = genai.GenerativeModel('gemini-1.5-flash')
        header_title = report_type.upper() + " ANALİZİ"
        
        prompt = f"""
        Sen kıdemli bir finansal analistsin. Bir İşletme Mühendisi için profesyonel analiz yap.
        
        KURALLAR:
        1. Başlık: **{header_title}**
        2. Tarih: _{datetime.now().strftime("%d.%m.%Y")} tarihli rapor özeti_
        3. Giriş nezaket cümlelerini (Merhaba, Sayın vb.) KULLANMA.
        4. TABLOLARI (Piyasa Verileri, Ajanda vb.) mutlaka ``` (triple backticks) içine al.
        5. En sona şu başlığı ekle: **📊 TREND VE ÖNCEKİ RAPORLA KIYASLAMA**
        
        ÖNCEKİ ÖZET: {previous_summary if previous_summary else "İlk veri."}
        RAPOR METNİ: {current_pdf_text[:12000]}
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
        page = browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
        
        try:
            print(f"--- Siteye Gidiliyor: {bugun_sayi} ---")
            page.goto("[https://www.garantibbvayatirim.com.tr/arastirma-raporlari](https://www.garantibbvayatirim.com.tr/arastirma-raporlari)", wait_until="domcontentloaded")
            page.wait_for_timeout(10000)
            
            items = page.query_selector_all(".reports-list-item")
            print(f"--- Sitede {len(items)} adet rapor bulundu ---")

            for target_title, report_key in targets.items():
                for item in items:
                    text = item.inner_text().lower()
                    if target_title in text and (bugun_sayi in text or bugun_metin in text):
                        
                        if history.get(f"{report_key}_LAST_DATE") != bugun_sayi:
                            print(f"--- {target_title} İşleniyor... ---")
                            link = item.query_selector("a.report-download")
                            if link:
                                url = link.get_attribute("href")
                                if not url.startswith("http"): url = "[https://www.garantibbvayatirim.com.tr](https://www.garantibbvayatirim.com.tr)" + url
                                
                                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
                                temp_pdf = f"temp_{report_key}.pdf"
                                with open(temp_pdf, "wb") as f: f.write(resp.content)
                                
                                with pdfplumber.open(temp_pdf) as pdf:
                                    raw_text = "".join(p.extract_text() for p in pdf.pages[:4])
                                
                                # Gemini Kota (429) koruması için kısa bekleme
                                time.sleep(2)
                                analysis = get_ai_analysis(raw_text, history.get(f"{report_key}_SUMMARY", ""), target_title)
                                
                                if "ERROR_CODE_GEMINI" not in analysis and "429" not in analysis:
                                    send_telegram(analysis)
                                    history[f"{report_key}_LAST_DATE"] = bugun_sayi
                                    history[f"{report_key}_SUMMARY"] = analysis
                                    print(f"--- {target_title} BAŞARIYLA GÖNDERİLDİ ---")
                                else:
                                    print(f"!!! KOTA VEYA GEMINI HATASI: {analysis[:100]} !!!")
                                break
        except Exception as e:
            print(f"HATA: {e}")
        finally:
            with open(history_file, "w") as f:
                json.dump(history, f)
            browser.close()

if __name__ == "__main__":
    process_automation()
