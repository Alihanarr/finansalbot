import os
import requests
import json
import pdfplumber
import google.generativeai as genai
from playwright.sync_api import sync_playwright
from datetime import datetime
import time

# Yapılandırmalar
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"].strip() # Boşluk veya parantez kalmasın diye strip ekledik
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"].strip()

def send_telegram(message):
    """Mesajı parçalara bölerek Telegram'a gönderir."""
    # URL'yi parantez hatası olmayacak şekilde en temiz haliyle kuruyoruz
    url = f"[https://api.telegram.org/bot](https://api.telegram.org/bot){TELEGRAM_TOKEN}/sendMessage"
    
    limit = 4000
    parts = [message[i:i+limit] for i in range(0, len(message), limit)]
    
    for part in parts:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID, 
            "text": part, 
            "parse_mode": "Markdown"
        }
        try:
            resp = requests.post(url, json=payload)
            if resp.status_code != 200:
                # Markdown hatası olursa düz metin gönder
                requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": part})
            print(f"DEBUG: Telegram Yanıtı: {resp.status_code}")
        except Exception as e:
            print(f"!!! Telegram Gönderim Hatası: {e}")
        time.sleep(1.5)

def get_ai_analysis(current_pdf_text, previous_summary, report_type):
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        selected = 'models/gemini-1.5-flash' if 'models/gemini-1.5-flash' in available_models else available_models[0]
        
        model = genai.GenerativeModel(selected)
        header_title = report_type.upper() + " ANALİZİ"
        
        prompt = f"""
        Sen kıdemli bir finansal analistsin. Bir İşletme Mühendisi için profesyonel analiz yap.
        
        FORMAT KURALLARI:
        1. Mesaja doğrudan şu başlıkla başla: **{header_title}**
        2. Altına: _{datetime.now().strftime("%d.%m.%Y")} tarihli rapor özeti_
        3. Giriş nezaket cümlelerini ASLA kullanma.
        4. TÜM TABLOLARI (Piyasa Verileri, Ajanda vb.) mutlaka ``` (üç ters tırnak) içine al.
        5. En sona şu başlığı ekle: **📊 TREND VE ÖNCEKİ RAPORLA KIYASLAMA**
        
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
        context = browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
        page = context.new_page()
        
        try:
            page.goto("https://www.garantibbvayatirim.com.tr/arastirma-raporlari", wait_until="domcontentloaded")
            page.wait_for_timeout(10000)
            
            items = page.query_selector_all(".reports-list-item")
            print(f"Sitede {len(items)} adet rapor bulundu.")

            for target_title, report_key in targets.items():
                for item in items:
                    text = item.inner_text().lower()
                    if target_title in text and (bugun_sayi in text or bugun_metin in text):
                        
                        if history.get(f"{report_key}_LAST_DATE") != bugun_sayi:
                            link = item.query_selector("a.report-download")
                            if link:
                                url = link.get_attribute("href")
                                if not url.startswith("http"): url = "https://www.garantibbvayatirim.com.tr" + url
                                
                                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
                                temp_pdf = f"temp_{report_key}.pdf"
                                with open(temp_pdf, "wb") as f: f.write(resp.content)
                                
                                with pdfplumber.open(temp_pdf) as pdf:
                                    raw_text = "".join(p.extract_text() for p in pdf.pages[:4])
                                
                                analysis = get_ai_analysis(raw_text, history.get(f"{report_key}_SUMMARY", ""), target_title)
                                
                                if "ERROR_CODE_GEMINI" not in analysis and "429" not in analysis:
                                    send_telegram(analysis)
                                    history[f"{report_key}_LAST_DATE"] = bugun_sayi
                                    history[f"{report_key}_SUMMARY"] = analysis
                                    print(f"--- {target_title} Başarıyla Gönderildi ---")
                                else:
                                    print(f"!!! ANALİZ YAPILAMADI (Kota veya Gemini Hatası) !!!")
                                break
        except Exception as e:
            print(f"HATA: {e}")
        finally:
            with open(history_file, "w") as f:
                json.dump(history, f)
            browser.close()

if __name__ == "__main__":
    process_automation()
