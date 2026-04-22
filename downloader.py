import os
import requests
import json
import pdfplumber
import google.generativeai as genai
from playwright.sync_api import sync_playwright
from datetime import datetime
import time

# 1. GÜVENLİ YAPILANDIRMA VE TEMİZLEME
def clean_env(key):
    val = os.environ.get(key, "")
    # Secret içindeki olası parantez/tırnak hatalarını temizler
    return str(val).strip().replace("[", "").replace("]", "").replace("'", "").replace('"', "")

genai.configure(api_key=clean_env("GEMINI_API_KEY"))
TELEGRAM_TOKEN = clean_env("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = clean_env("TELEGRAM_CHAT_ID")

# 2. MESAJ GÖNDERİMİ (PARÇALAMA VE FORMAT)
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    limit = 4000
    parts = [message[i:i+limit] for i in range(0, len(message), limit)]
    
    for idx, part in enumerate(parts):
        # Eğer parça sayısı birden fazlaysa başına bilgi koy
        p_info = f"*(Devamı {idx+1}/{len(parts)})*\n\n" if len(parts) > 1 else ""
        payload = {
            "chat_id": TELEGRAM_CHAT_ID, 
            "text": p_info + part, 
            "parse_mode": "Markdown"
        }
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code != 200:
                # Markdown hatası olursa düz metin gönder
                requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": part})
        except Exception as e:
            print(f"!!! Telegram Hatası: {e}")
        time.sleep(1.5)

# 3. GEMİNİ ANALİZ MOTORU (FULL ÖZELLİKLİ PROMPT)
def get_ai_analysis(pdf_text, prev_sum, r_type):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        header_title = r_type.upper() + " ANALİZİ"
        
        prompt = f"""
        Sen kıdemli bir finansal analistsin. Bir İşletme Mühendisi için raporu analiz et.
        
        KURALLAR:
        1. Başlık: **{header_title}**
        2. Tarih: _{datetime.now().strftime("%d.%m.%Y")} tarihli rapor özeti_
        3. Giriş nezaket cümlelerini (Merhaba, Sayın vb.) ASLA KULLANMA.
        4. TABLOLARI mutlaka ``` (üç adet ters tırnak) içine al. Bu çok kritik, tablolar monospace olmalı.
        5. Başlıkları **KALIN** yap.
        6. **📊 TREND VE ÖNCEKİ RAPORLA KIYASLAMA**: Bu bölümü EN SONDA ayrı bir başlık olarak yap. Önceki özetle ne değiştiğini (risk iştahı, teknik seviyeler vb.) net açıkla.
        
        KIYASLANACAK ÖZET: {prev_sum if prev_sum else "İlk veri kaydı."}
        METİN: {pdf_text[:12000]}
        """
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"ERROR_CODE_GEMINI: {str(e)}"

# 4. ANA OTOMASYON
def process_automation():
    targets = {"günlük piyasa özeti": "SABAH_RAPORU", "gün ortası notları": "OGLE_RAPORU"}
    bugun_sayi = datetime.now().strftime("%d.%m.%Y")
    
    # Tarih hazırlığı (Sitedeki 22 Nisan gibi metinsel tarihleri yakalamak için)
    aylar = {"01":"Ocak","02":"Şubat","03":"Mart","04":"Nisan","05":"Mayıs","06":"Haziran",
             "07":"Temmuz","08":"Ağustos","09":"Eylül","10":"Ekim","11":"Kasım","12":"Aralık"}
    bugun_metin = f"{datetime.now().strftime('%d')} {aylar[datetime.now().strftime('%m')]}".lower()

    history_file = "history.json"
    history = json.load(open(history_file)) if os.path.exists(history_file) else {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
        
        # URL TERTEMİZ: BAŞINDA VEYA SONUNDA PARANTEZ OLMADIĞINDAN EMİN OL
        site_url = "https://www.garantibbvayatirim.com.tr/arastirma-raporlari"
        
        try:
            print(f"--- Siteye Gidiliyor: {site_url} ---")
            page.goto(site_url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(5000)
            
            items = page.query_selector_all(".reports-list-item")
            print(f"Sitede {len(items)} adet rapor bulundu.")

            for target_title, report_key in targets.items():
                for item in items:
                    text = item.inner_text().lower()
                    
                    # Hem sayısal hem metin tarih kontrolü
                    if target_title in text and (bugun_sayi in text or bugun_metin in text):
                        if history.get(f"{report_key}_LAST_DATE") != bugun_sayi:
                            print(f"--- {target_title} İşleniyor... ---")
                            link = item.query_selector("a.report-download")
                            if link:
                                pdf_url = link.get_attribute("href")
                                if not pdf_url.startswith("http"):
                                    pdf_url = "https://www.garantibbvayatirim.com.tr" + pdf_url
                                
                                resp = requests.get(pdf_url)
                                with open("temp.pdf", "wb") as f: f.write(resp.content)
                                
                                with pdfplumber.open("temp.pdf") as pdf:
                                    # İlk 4 sayfayı oku
                                    raw_text = "".join(p.extract_text() for p in pdf.pages[:4])
                                
                                time.sleep(2) # Kota koruması için kısa bekleme
                                analysis = get_ai_analysis(raw_text, history.get(f"{report_key}_SUMMARY", ""), target_title)
                                
                                if "ERROR" not in analysis and "429" not in analysis:
                                    send_telegram(analysis)
                                    history[f"{report_key}_LAST_DATE"] = bugun_sayi
                                    history[f"{report_key}_SUMMARY"] = analysis
                                    print(f"--- {target_title} BAŞARIYLA TAMAMLANDI ---")
                                else:
                                    print(f"!!! GEMINI HATASI: {analysis[:100]} !!!")
                                break
        except Exception as e:
            print(f"KRİTİK HATA: {e}")
        finally:
            with open(history_file, "w") as f:
                json.dump(history, f)
            browser.close()

if __name__ == "__main__":
    process_automation()
