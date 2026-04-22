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
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

def send_telegram(message):
    """Mesajı parçalara bölerek ve Markdown formatıyla Telegram'a gönderir."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    # Telegram 4096 karakter sınırı olduğu için 4000'erlik parçalara bölüyoruz
    limit = 4000
    parts = [message[i:i+limit] for i in range(0, len(message), limit)]
    
    for idx, part in enumerate(parts):
        # Eğer birden fazla parça varsa başına ek bilgi koyalım
        header = f"*(Parça {idx+1}/{len(parts)})*\n\n" if len(parts) > 1 else ""
        payload = {
            "chat_id": TELEGRAM_CHAT_ID, 
            "text": header + part, 
            "parse_mode": "Markdown"
        }
        try:
            resp = requests.post(url, json=payload)
            if resp.status_code != 200:
                # Markdown hatası olursa düz metin olarak tekrar dene
                requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": part})
        except Exception as e:
            print(f"Telegram hatası: {e}")
        time.sleep(1) # Mesajların sırasının karışmaması için kısa bekleme

def get_ai_analysis(current_pdf_text, previous_summary, report_type):
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        selected = 'models/gemini-1.5-flash' if 'models/gemini-1.5-flash' in available_models else available_models[0]
        
        model = genai.GenerativeModel(selected)
        bugun = datetime.now().strftime("%d %B %Y") # Gemini'nin Türkçe ay ismini doğru kullanması için
        
        prompt = f"""
        Sen kıdemli bir finansal analistsin. Bir İşletme Mühendisi ve SPL Düzey 1 sahibi bir profesyonel için bu raporu analiz et.
        
        ÖNEMLİ KURALLAR:
        1. Asla 'Sayın İşletme Mühendisi' veya 'Merhaba' gibi giriş cümleleri kullanma.
        2. Doğrudan şu başlıkla başla: '*{datetime.now().strftime("%d.%m.%Y")} tarihli {report_type} raporu*'
        3. Tüm ana başlıkları ve önemli finansal terimleri (BIST100, faiz oranı, hisse kodları vb.) çift yıldız (**Örn**) kullanarak KALIN yaz.
        4. Hisse haberlerini 📈 (+) veya 📉 (-) şeklinde gruplandır.
        5. Teknik seviyeleri tablo gibi düzenli göster.
        
        KIYASLAMA VERİSİ: {previous_summary if previous_summary else "İlk veri."}
        METİN: {current_pdf_text[:12000]}
        """
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini Analiz Hatası: {str(e)}"

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
        
        page.goto("https://www.garantibbvayatirim.com.tr/arastirma-raporlari", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(10000)
        
        items = page.query_selector_all(".reports-list-item")
        
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
                            send_telegram(analysis)
                            
                            history[f"{report_key}_LAST_DATE"] = bugun_sayi
                            history[f"{report_key}_SUMMARY"] = analysis
                            break
        
        with open(history_file, "w") as f:
            json.dump(history, f)
        browser.close()

if __name__ == "__main__":
    process_automation()
