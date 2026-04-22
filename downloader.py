import os
import requests
import json
import pdfplumber
import google.generativeai as genai
from playwright.sync_api import sync_playwright
from datetime import datetime
import time

# 1. GÜVENLİ YAPILANDIRMA
def clean_env(key):
    val = os.environ.get(key, "")
    return str(val).strip().replace("[", "").replace("]", "").replace("'", "").replace('"', "")

genai.configure(api_key=clean_env("GEMINI_API_KEY"))
TELEGRAM_TOKEN = clean_env("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = clean_env("TELEGRAM_CHAT_ID")

# 2. MESAJ GÖNDERİMİ (İLK MESAJDA NUMARA YOK)
def send_telegram(message):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    limit = 4000
    parts = [message[i:i+limit] for i in range(0, len(message), limit)]
    
    for idx, part in enumerate(parts):
        # SADECE 2. parçadan itibaren numara (Devamı 2/3 vb.) ekliyoruz
        header = f"*(Devamı {idx+1}/{len(parts)})*\n\n" if idx > 0 else ""
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": header + part, "parse_mode": "Markdown"}
        try:
            resp = requests.post(api_url, json=payload, timeout=30)
            if resp.status_code != 200:
                print(f"!!! Telegram Markdown Reddi, Düz Metin Deneniyor... Status: {resp.status_code}")
                requests.post(api_url, json={"chat_id": TELEGRAM_CHAT_ID, "text": part}, timeout=30)
        except Exception as e:
            print(f"!!! Telegram Gönderim Hatası: {e}")
        time.sleep(2)

# 3. GEMİNİ 2.5 ANALİZ MOTORU (DETAYLI VE ŞIK)
def get_ai_analysis(pdf_text, prev_sum, r_type):
    try:
        # En güncel model ismi: models/gemini-2.5-flash
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        display_title = "GÜNLÜK PIYASA ÖZETİ ANALİZİ" if "piyasa" in r_type.lower() else "GÜN ORTASI NOTLARI ANALİZİ"
        
        prompt = f"""
        Sen kıdemli bir finansal analistsin. Bir İşletme Mühendisi ve SPL Düzey 1 sahibi profesyonel için üst düzey analiz yap.
        
        GÖRSEL KURALLAR:
        1. Mesaja doğrudan şu başlıkla başla: **{display_title}**
        2. Hemen altına: _{datetime.now().strftime("%d.%m.%Y")} tarihli rapor özeti_
        3. Giriş nezaket cümleleri (Merhaba, Sayın vb.) ASLA KULLANMA.
        4. Tüm tabloları (Piyasa Verileri, Seviyeler, Ajanda) mutlaka ``` (triple backticks) içine al.
        5. Kritik haberleri 📈 (+) veya 📉 (-) ikonlarıyla ve **KALIN** başlıklarla ver.
        
        İÇERİK BEKLENTİSİ:
        - BIST100 Teknik Seviyeler ve Kırılma Noktaları.
        - Önemli Makro Gelişmeler.
        - **📊 TREND VE ÖNCEKİ RAPORLA KIYASLAMA**: En sonda dünkü veya sabahki raporla bugünkü arasındaki farkları (örneğin sabah bahsettiğimiz seviye şimdi geçildi gibi) analiz et.
        
        ÖNCEKİ ÖZET: {prev_sum if prev_sum else "İlk analiz verisi."}
        METİN: {pdf_text[:15000]}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"ERROR_CODE_GEMINI: {str(e)}"

# 4. ANA OTOMASYON
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
        
        print(f"--- 1. Siteye Gidiliyor... ---")
        page.goto("https://www.garantibbvayatirim.com.tr/arastirma-raporlari", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(10000)
        
        items = page.query_selector_all(".reports-list-item")
        print(f"--- 2. Sitede {len(items)} adet rapor bulundu. ---")

        for target_title, report_key in targets.items():
            found_today = False
            for item in items:
                text = item.inner_text().lower()
                if target_title in text and (bugun_sayi in text or bugun_metin in text):
                    found_today = True
                    if history.get(f"{report_key}_LAST_DATE") != bugun_sayi:
                        print(f"--- 3. {target_title} İşleniyor... ---")
                        link = item.query_selector("a.report-download")
                        if link:
                            pdf_url = link.get_attribute("href")
                            if not pdf_url.startswith("http"):
                                pdf_url = "https://www.garantibbvayatirim.com.tr" + pdf_url
                            
                            resp = requests.get(pdf_url)
                            with open("temp.pdf", "wb") as f: f.write(resp.content)
                            with pdfplumber.open("temp.pdf") as pdf:
                                raw_text = "".join(p.extract_text() for p in pdf.pages[:5])
                            
                            time.sleep(3)
                            analysis = get_ai_analysis(raw_text, history.get(f"{report_key}_SUMMARY", ""), target_title)
                            
                            # ANALİZ SONUCUNU LOGLA (SORUNU GÖREBİLMEK İÇİN)
                            if "ERROR" in analysis or "429" in analysis:
                                print(f"!!! {target_title} İÇİN GEMINI HATASI: {analysis}")
                            else:
                                send_telegram(analysis)
                                history[f"{report_key}_LAST_DATE"] = bugun_sayi
                                history[f"{report_key}_SUMMARY"] = analysis
                                print(f"--- 4. {target_title} BAŞARIYLA GÖNDERİLDİ ---")
                        break
            if not found_today:
                print(f"BİLGİ: {target_title} için bugüne ait rapor henüz bulunamadı.")
        
        with open(history_file, "w") as f:
            json.dump(history, f)
        browser.close()

if __name__ == "__main__":
    process_automation()
