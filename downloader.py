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
    try:
        resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})
        resp.raise_for_status()
    except Exception as e:
        print(f"Telegram gönderim hatası: {e}")

def get_ai_analysis(current_pdf_text, previous_summary, report_type):
    # Model ismini en güncel ve kararlı haliyle çağırıyoruz
    model = genai.GenerativeModel(model_name='gemini-1.5-flash')
    
    prompt = f"""
    Sen üst düzey bir finansal analistsin. Bir İşletme Mühendisi ve SPL Düzey 1 sahibi bir profesyonel için aşağıdaki {report_type} raporunu analiz et.
    
    FORMAT ŞARTLARI:
    1. MANŞET: En kritik gelişmeyi vurgulayan iddialı bir başlık.
    2. KÜRESEL & MAKRO: Jeopolitik riskler ve faiz beklentileri.
    3. TEKNİK SEVİYELER: BIST100 ve VİOP destek/direnç noktaları.
    4. ÖNEMLİ HİSSE HABERLERİ: (+) ve (-) haberleri filtrele, 'Yükseliş/Düşüş Bekleniyor' notu ekle.
    5. TREND & KIYASLAMA: Aşağıdaki 'Önceki Rapor Özeti' ile karşılaştır.
    
    ÖNCEKİ ÖZET: {previous_summary if previous_summary else "İlk veri."}
    METİN: {current_pdf_text[:12000]}
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini Analiz Hatası: {str(e)}"

def process_automation():
    targets = {
        "günlük piyasa özeti": "SABAH_RAPORU",
        "gün ortası notları": "OGLE_RAPORU"
    }
    
    # Tarih formatlarını hazırlıyoruz (22.04.2026 ve 22 nisan)
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
        # Gerçek bir kullanıcı gibi görünmek için ayarlar
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        print(f"--- Otomasyon Başladı: {datetime.now().strftime('%H:%M:%S')} ---")
        page.goto("https://www.garantibbvayatirim.com.tr/arastirma-raporlari", wait_until="domcontentloaded", timeout=60000)
        
        # Sayfanın tam yüklenmesi için 10 saniye sabırla bekliyoruz
        page.wait_for_timeout(10000)
        
        items = page.query_selector_all(".reports-list-item")
        print(f"Sitede toplam {len(items)} adet rapor kutusu bulundu.")

        for target_title, report_key in targets.items():
            for item in items:
                item_text = item.inner_text().lower()
                
                # Hem sayısal hem metinsel tarih kontrolü
                if target_title in item_text and (bugun_sayisal in item_text or bugun_metin in item_text):
                    print(f"EŞLEŞME BULDUM: {target_title}")
                    
                    # Eğer bugün bu raporu zaten işlemediysek
                    if history.get(f"{report_key}_LAST_DATE") != bugun_sayisal:
                        link_element = item.query_selector("a.report-download")
                        if link_element:
                            url = link_element.get_attribute("href")
                            if not url.startswith("http"):
                                url = "https://www.garantibbvayatirim.com.tr" + url
                            
                            # PDF İndir
                            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
                            temp_pdf = f"{report_key}.pdf"
                            with open(temp_pdf, "wb") as f:
                                f.write(resp.content)
                            
                            # PDF Oku
                            with pdfplumber.open(temp_pdf) as pdf:
                                current_text = "".join(p.extract_text() for p in pdf.pages[:4])
                            
                            # Gemini Analizi
                            prev_summary = history.get(f"{report_key}_SUMMARY", "")
                            analysis = get_ai_analysis(current_text, prev_summary, target_title)
                            
                            # Telegram Mesajı
                            final_message = f"📊 *{target_title.upper()}*\n\n{analysis}"
                            send_telegram(final_message)
                            
                            # Hafızayı Güncelle
                            history[f"{report_key}_LAST_DATE"] = bugun_sayisal
                            history[f"{report_key}_SUMMARY"] = analysis
                            print(f"--- {target_title} İşlendi ve Telegram'a Gönderildi ---")
                            break
        
        # Son durumu kaydet
        with open(history_file, "w") as f:
            json.dump(history, f)
            
        browser.close()

if __name__ == "__main__":
    process_automation()
