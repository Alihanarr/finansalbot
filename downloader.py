import os, requests, json, pdfplumber
import google.generativeai as genai
from playwright.sync_api import sync_playwright
from datetime import datetime

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})

def get_ai_analysis(text, prev, r_type):
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"Analist olarak bu {r_type} raporunu özetle ve şu önceki özetle kıyasla: {prev}. Metin: {text[:10000]}"
    return model.generate_content(prompt).text

def process_automation():
    targets = {"günlük piyasa özeti": "SABAH_RAPORU", "gün ortası notları": "OGLE_RAPORU"}
    bugun_sayi = datetime.now().strftime("%d.%m.%Y")
    history_file = "history.json"
    history = json.load(open(history_file)) if os.path.exists(history_file) else {}

    with sync_playwright() as p:
        # Daha 'insansı' bir tarayıcı profili
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        print(f"--- Siteye gidiliyor: {datetime.now().strftime('%H:%M:%S')} ---")
        
        try:
            # Sayfaya git ve biraz bekle
            page.goto("https://www.garantibbvayatirim.com.tr/arastirma-raporlari", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(10000) # 10 saniye sabırla bekle
            
            print(f"SAYFA BAŞLIĞI: {page.title()}")
            
            # Eğer boş sayfa geliyorsa içeriğin bir kısmını yazdır (Teşhis için)
            content_snippet = page.content()[:500].replace('\n', ' ')
            print(f"SAYFA ÖNİZLEME: {content_snippet}")

            # Raporları bulmak için daha genel bir selector deniyoruz
            items = page.query_selector_all("div.reports-list-item, .reports-list-item")
            print(f"Sitede toplam {len(items)} adet rapor kutusu bulundu.")

            if len(items) == 0:
                print("KRİTİK UYARI: Hiç rapor bulunamadı! Sayfa yapısı değişmiş veya erişim engellenmiş olabilir.")

            for target_title, report_key in targets.items():
                for item in items:
                    text = item.inner_text().lower()
                    if target_title in text and bugun_sayi in text:
                        if history.get(f"{report_key}_LAST_DATE") != bugun_sayi:
                            print(f"BULDUM: {target_title}")
                            link = item.query_selector("a.report-download")
                            if link:
                                url = link.get_attribute("href")
                                if not url.startswith("http"): url = "https://www.garantibbvayatirim.com.tr" + url
                                
                                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
                                with open("temp.pdf", "wb") as f: f.write(resp.content)
                                
                                with pdfplumber.open("temp.pdf") as pdf:
                                    raw_text = "".join(p.extract_text() for p in pdf.pages[:4])
                                
                                analysis = get_ai_analysis(raw_text, history.get(f"{report_key}_SUMMARY", ""), target_title)
                                send_telegram(f"📊 *{target_title.upper()}*\n\n{analysis}")
                                
                                history[f"{report_key}_LAST_DATE"] = bugun_sayi
                                history[f"{report_key}_SUMMARY"] = analysis
                                break
            
            with open(history_file, "w") as f: json.dump(history, f)
            
        except Exception as e:
            print(f"HATA OLUŞTU: {str(e)}")
        finally:
            browser.close()

if __name__ == "__main__":
    process_automation()
