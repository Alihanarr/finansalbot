import requests
from playwright.sync_api import sync_playwright
from datetime import datetime
import os

def download_reports():
    # Aranacak başlıklar
    targets = ["günlük piyasa özeti", "gün ortası notları"]
    bugun = datetime.now().strftime("%d.%m.%Y") # Örn: 22.04.2026
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0")
        page = context.new_page()
        
        try:
            page.goto("https://www.garantibbvayatirim.com.tr/arastirma-raporlari", wait_until="networkidle")
            page.wait_for_selector(".reports-list-item")
            items = page.query_selector_all(".reports-list-item")
            
            for target_title in targets:
                for item in items:
                    item_text = item.inner_text().lower()
                    # Hem başlık uymalı hem de içinde bugünün tarihi geçmeli
                    if target_title in item_text and bugun in item_text:
                        download_btn = item.query_selector("a.report-download")
                        if download_btn:
                            report_url = download_btn.get_attribute("href")
                            if not report_url.startswith("http"):
                                report_url = "https://www.garantibbvayatirim.com.tr" + report_url
                            
                            # İndirme işlemi
                            resp = requests.get(report_url)
                            filename = f"{target_title.replace(' ', '_')}_{bugun}.pdf"
                            with open(filename, "wb") as f:
                                f.write(resp.content)
                            print(f"Bulundu ve indirildi: {filename}")
                            break # Bu başlık için en günceli bulduk, sonrakine geç
        except Exception as e:
            print(f"Hata: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    download_reports()
