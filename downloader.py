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
    prompt = f"Finansal Analist olarak bu {r_type} raporunu analiz et. Önceki özetle kıyasla: {prev}. Metin: {text[:10000]}"
    return model.generate_content(prompt).text

def process_automation():
    targets = {"günlük piyasa özeti": "SABAH_RAPORU", "gün ortası notları": "OGLE_RAPORU"}
    bugun_sayi = datetime.now().strftime("%d.%m.%Y")
    history_file = "history.json"
    history = json.load(open(history_file)) if os.path.exists(history_file) else {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # Bekleme süresini artırdık
        page.goto("https://www.garantibbvayatirim.com.tr/arastirma-raporlari", wait_until="load", timeout=60000)
        page.wait_for_timeout(5000) # Sayfanın tam oturması için 5 sn ek bekleme
        
        items = page.query_selector_all(".reports-list-item")
        print(f"Sitede toplam {len(items)} adet rapor kutusu bulundu.")

        for target_title, report_key in targets.items():
            for item in items:
                text = item.inner_text().lower()
                # Debug için her raporun ilk 50 karakterini yazdıralım
                print(f"Kontrol edilen: {text[:50].replace('', ' ')}")
                
                if target_title in text and bugun_sayi in text:
                    filename = f"{report_key}_{bugun_sayi}.pdf"
                    if history.get(f"{report_key}_LAST_DATE") != bugun_sayi:
                        print(f"--- {target_title.upper()} BULDUM, İŞLENİYOR ---")
                        url = item.query_selector("a.report-download").get_attribute("href")
                        if not url.startswith("http"): url = "https://www.garantibbvayatirim.com.tr" + url
                        
                        resp = requests.get(url)
                        with open(filename, "wb") as f: f.write(resp.content)
                        
                        with pdfplumber.open(filename) as pdf:
                            raw_text = "".join(p.extract_text() for p in pdf.pages[:4])
                        
                        analysis = get_ai_analysis(raw_text, history.get(f"{report_key}_SUMMARY", ""), target_title)
                        send_telegram(f"🚀 *{target_title.upper()} ANALİZİ*\n\n" + analysis)
                        
                        history[f"{report_key}_LAST_DATE"] = bugun_sayi
                        history[f"{report_key}_SUMMARY"] = analysis
                        break
        
        with open(history_file, "w") as f: json.dump(history, f)
        browser.close()

if __name__ == "__main__":
    process_automation()
