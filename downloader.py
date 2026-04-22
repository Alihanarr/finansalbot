import requests
from playwright.sync_api import sync_playwright
from datetime import datetime
import os

def download_reports():
    targets = ["günlük piyasa özeti", "gün ortası notları"]
    bugun = datetime.now().strftime("%d.%m.%Y")
    history_file = "history.txt"
    
    # Geçmişte gönderilenleri oku
    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            sent_reports = f.read().splitlines()
    else:
        sent_reports = []

    new_downloads = False
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            page.goto("https://www.garantibbvayatirim.com.tr/arastirma-raporlari", wait_until="networkidle")
            items = page.query_selector_all(".reports-list-item")
            
            for target_title in targets:
                for item in items:
                    item_text = item.inner_text().lower()
                    if target_title in item_text and bugun in item_text:
                        filename = f"{target_title.replace(' ', '_')}_{bugun}.pdf"
                        
                        # EĞER BU DOSYAYI DAHA ÖNCE GÖNDERMEDİYSEK
                        if filename not in sent_reports:
                            download_btn = item.query_selector("a.report-download")
                            if download_btn:
                                report_url = download_btn.get_attribute("href")
                                if not report_url.startswith("http"):
                                    report_url = "https://www.garantibbvayatirim.com.tr" + report_url
                                
                                resp = requests.get(report_url)
                                with open(filename, "wb") as f:
                                    f.write(resp.content)
                                
                                # Geçmişe ekle
                                with open(history_file, "a") as f:
                                    f.write(filename + "\n")
                                
                                print(f"Yeni rapor bulundu: {filename}")
                                new_downloads = True
                            break 
            
        except Exception as e:
            print(f"Hata: {e}")
        finally:
            browser.close()
    
    return new_downloads

if __name__ == "__main__":
    download_reports()
