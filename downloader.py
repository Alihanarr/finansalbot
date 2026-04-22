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
        # Mesajı Markdown formatında gönderiyoruz (Başlıklar ve kalın yazılar için)
        resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})
        resp.raise_for_status()
    except Exception as e:
        print(f"Telegram gönderim hatası: {e}")

def get_ai_analysis(current_pdf_text, previous_summary, report_type):
    """Gemini Flash modelini kullanarak finansal analiz yapar."""
    try:
        # 2026'nın en güncel model ismi çağrısı
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
        Sen kıdemli bir finansal analistsin. Bir İşletme Mühendisi ve SPL Düzey 1 sahibi bir profesyonel için aşağıdaki {report_type} raporunu analiz et.
        
        FORMAT ŞARTLARI:
        1. MANŞET: En kritik gelişmeyi vurgulayan iddialı bir başlık.
        2. KÜRESEL & MAKRO: Jeopolitik riskler ve faiz beklentileri.
        3. TEKNİK SEVİYELER: BIST100 ve VİOP destek/direnç noktaları.
        4. ÖNEMLİ HİSSE HABERLERİ: (+) ve (-) haberleri filtrele, yanlarına 📈 veya 📉 koy.
        5. TREND & KIYASLAMA: Aşağıdaki önceki rapor özetiyle kıyaslayarak değişen sinyalleri belirt.
        
        ÖNCEKİ ÖZET: {previous_summary if previous_summary else "İlk rapor verisi."}
        GÜNCEL METİN: {current_pdf_text[:12000]}
        """
        
        response = model.generate_content(prompt)
        return response.text if response.text else "Analiz metni boş döndü."
    except Exception as e:
        return f"Gemini Analiz Hatası: {str(e)}"

def process_automation():
    targets = {
        "günlük piyasa özeti": "SABAH_RAPORU",
        "gün ortası notları": "OGLE_RAPORU"
    }
    
    # Bugünün tarihini hem sayısal hem metin olarak hazırlıyoruz
    bugun_sayisal = datetime.now().strftime("%d.%m.%Y")
    aylar = {"01":"Ocak","02":"Şubat","03":"Mart","04":"Nisan","05":"Mayıs","06":"Haziran",
             "07":"Temmuz","08":"Ağustos","09":"Eylül","10":"Ekim","11":"Kasım","12":"Aralık"}
    ay_ismi = aylar[datetime.now().strftime("%m")]
    bugun_metin = f"{datetime.now().strftime('%d')} {ay_ismi}".lower()

    history_file = "history.json"
    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            history = json.load(f)
    else:
        history = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        print(f"--- Bot Başlatıldı: {bugun_sayisal} ---")
        page.goto("https://www.garantibbvayatirim.com.tr/arastirma-raporlari", wait_until="domcontentloaded", timeout=60000)
        
        # Sayfanın tam yüklenmesi için 10 saniye bekleme
        page.wait_for_timeout(10000)
        
        items = page.query_selector_all(".reports-list-item")
        print(f"Sitede {len(items)} adet rapor bulundu.")

        for target_title, report_key in targets.items():
            for item in items:
                item_text = item.inner_text().lower()
                
                # Başlık ve tarih eşleşmesi (Hem sayı hem metin kontrolü)
                if target_title in item_text and (bugun_sayisal in item_text or bugun_metin in item_text):
                    # Hafıza kontrolü: Bugün bu rapor işlenmediyse
                    if history.get(f"{report_key}_LAST_DATE") != bugun_sayisal:
                        link_element = item.query_selector("a.report-download")
                        if link_element:
                            url = link_element.get_attribute("href")
                            if not url.startswith("http"):
                                url = "https://www.garantibbvayatirim.com.tr" + url
                            
                            print(f"İndiriliyor: {target_title}")
                            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
                            temp_file = f"{report_key}.pdf"
                            with open(temp_file, "wb") as f:
                                f.write(resp.content)
                            
                            with pdfplumber.open(temp_file) as pdf:
                                raw_text = "".join(p.extract_text() for p in pdf.pages[:4])
                            
                            # Gemini Analizi
                            prev_summary = history.get(f"{report_key}_SUMMARY", "")
                            analysis = get_ai_analysis(raw_text, prev_summary, target_title)
                            
                            # Telegram'a Gönder
                            final_message = f"📊 *{target_title.upper()} ANALİZİ*\n\n{analysis}"
                            send_telegram(final_message)
                            
                            # Hafızayı Güncelle
                            history[f"{report_key}_LAST_DATE"] = bugun_sayisal
                            history[f"{report_key}_SUMMARY"] = analysis
                            print(f"--- {target_title} İşlendi ---")
                            break
        
        with open(history_file, "w") as f:
            json.dump(history, f)
            
        browser.close()

if __name__ == "__main__":
    process_automation()
