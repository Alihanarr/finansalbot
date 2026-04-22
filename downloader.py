import os
import requests
import json
import pdfplumber
import google.generativeai as genai
from playwright.sync_api import sync_playwright
from datetime import datetime

# API Yapılandırması
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # Sorunu anlamak için önce formatlamasız (düz metin) deniyoruz
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": message[:4000] # Karakter sınırını aşmaması için kestik
    }
    try:
        resp = requests.post(url, json=payload)
        print(f"DEBUG: Telegram Yanıt Kodu: {resp.status_code}")
        print(f"DEBUG: Telegram Sunucu Mesajı: {resp.text}")
        
        # Eğer Markdown hatasıysa düz metin olarak tekrar dene
        if resp.status_code != 200:
            print("DEBUG: Markdown hatası olabilir, düz metin deneniyor...")
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": "ANALİZ HATASI: Format uyumsuzluğu, lütfen logları kontrol et."})
    except Exception as e:
        print(f"!!! Telegram Bağlantı Hatası: {e}")

def get_ai_analysis(current_pdf_text, previous_summary, report_type):
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # En stabil modelde sabitleyelim
        selected = 'models/gemini-1.5-flash'
        if selected not in available_models:
            selected = available_models[0]
        
        print(f"DEBUG: Analiz İçin Seçilen Model: {selected}")
        model = genai.GenerativeModel(selected)
        
        prompt = f"""
        Sen kıdemli bir analistsin. Bir İşletme Mühendisi için bu {report_type} raporunu özetle.
        KIYASLAMA: {previous_summary if previous_summary else "İlk veri."}
        METİN: {current_pdf_text[:10000]}
        """
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"DEBUG: Gemini Analiz Hatası: {str(e)}"

def process_automation():
    targets = {"günlük piyasa özeti": "SABAH_RAPORU", "gün ortası notları": "OGLE_RAPORU"}
    bugun_sayi = datetime.now().strftime("%d.%m.%Y")
    
    aylar = {"01":"Ocak","02":"Şubat","03":"Mart","04":"Nisan","05":"Mayıs","06":"Haziran",
             "07":"Temmuz","08":"Ağustos","09":"Eylül","10":"Ekim","11":"Kasım","12":"Aralık"}
    bugun_metin = f"{datetime.now().strftime('%d')} {aylar[datetime.now().strftime('%m')]}".lower()

    history_file = "history.json"
    history = json.load(open(history_file)) if os.path.exists(history_file) else {}

    with sync_playwright() as p:
        print("--- 1. Playwright Başlatılıyor ---")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
        page = context.new_page()
        
        print(f"--- 2. Siteye Gidiliyor: {bugun_sayi} ---")
        page.goto("https://www.garantibbvayatirim.com.tr/arastirma-raporlari", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(10000)
        
        items = page.query_selector_all(".reports-list-item")
        print(f"--- 3. Sitede {len(items)} Rapor Görüldü ---")

        for target_title, report_key in targets.items():
            for item in items:
                text = item.inner_text().lower()
                if target_title in text and (bugun_sayi in text or bugun_metin in text):
                    
                    # Önceki başarılı denemeleri sildiysen burası hep çalışır
                    if history.get(f"{report_key}_LAST_DATE") != bugun_sayi:
                        print(f"!!! EŞLEŞME BULDUM: {target_title} !!!")
                        link = item.query_selector("a.report-download")
                        if link:
                            url = link.get_attribute("href")
                            if not url.startswith("http"): url = "https://www.garantibbvayatirim.com.tr" + url
                            
                            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
                            with open("temp.pdf", "wb") as f: f.write(resp.content)
                            
                            with pdfplumber.open("temp.pdf") as pdf:
                                raw_text = "".join(p.extract_text() for p in pdf.pages[:4])
                            
                            print("--- 4. Gemini Analiz Ediyor... ---")
                            analysis = get_ai_analysis(raw_text, history.get(f"{report_key}_SUMMARY", ""), target_title)
                            
                            print("--- 5. Telegram Mesajı Gönderiliyor... ---")
                            send_telegram(f"📊 {target_title.upper()} ANALİZİ\n\n{analysis}")
                            
                            history[f"{report_key}_LAST_DATE"] = bugun_sayi
                            history[f"{report_key}_SUMMARY"] = analysis
                            break
        
        with open(history_file, "w") as f: json.dump(history, f)
        browser.close()

if __name__ == "__main__":
    process_automation()
