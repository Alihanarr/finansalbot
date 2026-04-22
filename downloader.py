import os
import requests
import json
import pdfplumber
import google.generativeai as genai
from playwright.sync_api import sync_playwright
from datetime import datetime
import time

# ==========================================
# 1. GÜVENLİ YAPILANDIRMA VE TEMİZLEME
# ==========================================
def clean_env(key):
    """GitHub Secrets içindeki olası parantez/tırnak hatalarını temizler."""
    val = os.environ.get(key, "")
    return str(val).strip().replace("[", "").replace("]", "").replace("'", "").replace('"', "")

genai.configure(api_key=clean_env("GEMINI_API_KEY"))
TELEGRAM_TOKEN = clean_env("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = clean_env("TELEGRAM_CHAT_ID")

# ==========================================
# 2. MESAJ GÖNDERİMİ (ESTETİK NUMARALANDIRMA)
# ==========================================
def send_telegram(message):
    """Mesajı böler; 1. parçada numara yazmaz, sonrakilerde 'Devamı' yazar."""
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    limit = 4000
    parts = [message[i:i+limit] for i in range(0, len(message), limit)]
    
    for idx, part in enumerate(parts):
        # Mühendislik dokunuşu: Sadece 2. parçadan itibaren (idx > 0) numara koyuyoruz
        header = f"*(Devamı {idx+1}/{len(parts)})*\n\n" if idx > 0 else ""
        payload = {
            "chat_id": TELEGRAM_CHAT_ID, 
            "text": header + part, 
            "parse_mode": "Markdown"
        }
        try:
            resp = requests.post(api_url, json=payload, timeout=30)
            if resp.status_code != 200:
                # Markdown hatası (karakter uyuşmazlığı) olursa düz metin gönder
                requests.post(api_url, json={"chat_id": TELEGRAM_CHAT_ID, "text": part}, timeout=30)
        except Exception as e:
            print(f"!!! Telegram Gönderim Hatası: {e}")
        time.sleep(1.5)

# ==========================================
# 3. GEMİNİ 2.5 ANALİZ MOTORU (ÜST DÜZEY ANALİZ)
# ==========================================
def get_ai_analysis(pdf_text, prev_sum, r_type):
    """Her iki rapor tipini de profesyonel formatta analiz eder."""
    try:
        # Doğrudan Gemini 2.5 Flash modelini kullanıyoruz
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # Dinamik ve ayırt edici başlık belirleme
        display_title = "GÜNLÜK PIYASA ÖZETİ ANALİZİ" if "piyasa" in r_type.lower() else "GÜN ORTASI NOTLARI ANALİZİ"
        
        prompt = f"""
        Sen kıdemli bir finansal analistsin. Bir İşletme Mühendisi ve SPL Düzey 1 sahibi bir profesyonel için analiz yap.
        
        KURALLAR:
        1. Mesaja doğrudan şu başlıkla başla: **{display_title}**
        2. Altına: _{datetime.now().strftime("%d.%m.%Y")} tarihli rapor özeti_
        3. Giriş nezaket cümlelerini (Merhaba, Sayın vb.) ASLA KULLANMA.
        4. TÜM TABLOLARI (Piyasa Verileri, Destek/Direnç Seviyeleri, Ajanda) mutlaka ``` içine al.
        5. Kritik hisse haberlerini 📈 (+) veya 📉 (-) ikonlarıyla ve **KALIN** başlıklarla ver.
        
        İÇERİK BEKLENTİSİ:
        - Makro ekonomik görünümün BIST100 üzerindeki etkisi.
        - Teknik seviyeler (Destek/Direnç) ve kırılma noktaları.
        - **📊 TREND VE ÖNCEKİ RAPORLA KIYASLAMA**: En sonda dünkü veya sabahki raporla bugünkü arasındaki farkları teknik olarak analiz et.
        
        ÖNCEKİ ÖZET: {prev_sum if prev_sum else "İlk analiz verisi."}
        METİN: {pdf_text[:15000]}
        """
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"ERROR_CODE_GEMINI: {str(e)}"

# ==========================================
# 4. ANA OTOMASYON (URL DÜZELTİLDİ)
# ==========================================
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
        
        # URL'leri Markdown formatından kurtardım, artık tertemiz saf stringler:
        site_url = "https://www.garantibbvayatirim.com.tr/arastirma-raporlari"
        base_url = "https://www.garantibbvayatirim.com.tr"
        
        print(f"--- Siteye Gidiliyor: {site_url} ---")
        
        try:
            page.goto(site_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(10000)
            
            items = page.query_selector_all(".reports-list-item")
            for target_title, report_key in targets.items():
                for item in items:
                    text = item.inner_text().lower()
                    if target_title in text and (bugun_sayi in text or bugun_metin in text):
                        if history.get(f"{report_key}_LAST_DATE") != bugun_sayi:
                            print(f"--- {target_title} İşleniyor... ---")
                            link = item.query_selector("a.report-download")
                            if link:
                                pdf_url = link.get_attribute("href")
                                if not pdf_url.startswith("http"):
                                    pdf_url = base_url + pdf_url
                                
                                resp = requests.get(pdf_url)
                                with open("temp.pdf", "wb") as f: f.write(resp.content)
                                with pdfplumber.open("temp.pdf") as pdf:
                                    raw_text = "".join(p.extract_text() for p in pdf.pages[:5])
                                
                                time.sleep(3)
                                analysis = get_ai_analysis(raw_text, history.get(f"{report_key}_SUMMARY", ""), target_title)
                                
                                if "ERROR" not in analysis and "429" not in analysis:
                                    send_telegram(analysis)
                                    history[f"{report_key}_LAST_DATE"] = bugun_sayi
                                    history[f"{report_key}_SUMMARY"] = analysis
                                    print(f"--- {target_title} TAMAMLANDI ---")
                                break
        except Exception as e:
            print(f"KRİTİK HATA: {e}")
        finally:
            with open(history_file, "w") as f:
                json.dump(history, f)
            browser.close()

if __name__ == "__main__":
    process_automation()
