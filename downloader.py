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
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"!!! Telegram Hatası: {e}")

def get_ai_analysis(current_pdf_text, previous_summary, report_type):
    """Sistemdeki aktif modelleri tarayıp en uygun olanla analiz yapar."""
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        print(f"DEBUG: Erişilebilir Modeller Listesi: {available_models}")
        
        selected = None
        for m in ['models/gemini-1.5-flash', 'models/gemini-2.0-flash', 'models/gemini-2.5-flash']:
            if m in available_models:
                selected = m
                break
        if not selected: selected = available_models[0]
        
        print(f"DEBUG: Seçilen Model: {selected}")
        model = genai.GenerativeModel(selected)
        
        prompt = f"""
        Sen üst düzey bir finansal analistsin. Bu {report_type} raporunu özetle.
        KIYASLAMA: {previous_summary if previous_summary else "İlk veri."}
        METİN: {current_pdf_text[:12000]}
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
    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            history = json.load(f)
    else:
        history = {}
        print("DEBUG: history.json bulunamadı, yeni bir hafıza oluşturuluyor.")

    with sync_playwright() as p:
        print("--- 1. Playwright Başlatılıyor ---")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
        page = context.new_page()
        
        print(f"--- 2. Siteye Gidiliyor... Aranan Tarih: {bugun_sayi} / {bugun_metin} ---")
        page.goto("https://www.garantibbvayatirim.com.tr/arastirma-raporlari", wait_until="domcontentloaded", timeout=60000)
        
        print("--- 3. Sayfanın oturması için 10 saniye bekleniyor... ---")
        page.wait_for_timeout(10000)
        
        items = page.query_selector_all(".reports-list-item")
        print(f"--- 4. Sitede Toplam {len(items)} adet rapor kutusu görüldü. ---")

        for target_title, report_key in targets.items():
            print(f"DEBUG: Şu an aranan rapor tipi: {target_title}")
            found_item = False
            
            for item in items:
                text = item.inner_text().lower()
                
                if target_title in text and (bugun_sayi in text or bugun_metin in text):
                    found_item = True
                    print(f"!!! EŞLEŞME BULDUM: {target_title} !!!")
                    
                    # Hafıza Kontrolü
                    if history.get(f"{report_key}_LAST_DATE") == bugun_sayi:
                        print(f"SKİP: {target_title} bugün zaten başarıyla işlenmiş. Pas geçiliyor.")
                        break
                    
                    link = item.query_selector("a.report-download")
                    if link:
                        url = link.get_attribute("href")
                        if not url.startswith("http"): url = "https://www.garantibbvayatirim.com.tr" + url
                        
                        print(f"--- 5. PDF İndiriliyor: {url} ---")
                        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
                        with open("temp.pdf", "wb") as f: f.write(resp.content)
                        
                        print("--- 6. PDF Metni Okunuyor... ---")
                        with pdfplumber.open("temp.pdf") as pdf:
                            raw_text = "".join(p.extract_text() for p in pdf.pages[:4])
                        
                        print(f"--- 7. Gemini Analizi Başlatılıyor ({target_title})... ---")
                        analysis = get_ai_analysis(raw_text, history.get(f"{report_key}_SUMMARY", ""), target_title)
                        
                        print("--- 8. Telegram Mesajı Gönderiliyor... ---")
                        send_telegram(f"📊 *{target_title.upper()} ANALİZİ*\n\n{analysis}")
                        
                        history[f"{report_key}_LAST_DATE"] = bugun_sayi
                        history[f"{report_key}_SUMMARY"] = analysis
                        print(f"--- BAŞARILI: {target_title} için işlem tamamlandı. ---")
                        break
            
            if not found_item:
                print(f"DEBUG: Sitede '{target_title}' için bugüne ait bir kayıt bulunamadı.")
        
        with open(history_file, "w") as f:
            json.dump(history, f)
        
        print("--- 9. İşlem Bitti, Tarayıcı Kapatılıyor. ---")
        browser.close()

if __name__ == "__main__":
    process_automation()
