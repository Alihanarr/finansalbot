import requests
from playwright.sync_api import sync_playwright
from datetime import datetime
import os

def download_specific_report():
    target_title = "günlük piyasa özeti"
    
    with sync_playwright() as p:
        print(f"Sistem başlatıldı: '{target_title}' aranıyor...")
        # GitHub'da çalışırken 'headless' her zaman True olmalı
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
        page = context.new_page()
        
        try:
            url = "https://www.garantibbvayatirim.com.tr/arastirma-raporlari"
            page.goto(url, wait_until="networkidle", timeout=60000)
            
            page.wait_for_selector(".reports-list-item")
            items = page.query_selector_all(".reports-list-item")
            
            report_url = None
            
            for item in items:
                item_text = item.inner_text().lower().strip()
                if target_title in item_text:
                    download_btn = item.query_selector("a.report-download")
                    if download_btn:
                        report_url = download_btn.get_attribute("href")
                        break
            
            if report_url:
                if not report_url.startswith("http"):
                    report_url = "https://www.garantibbvayatirim.com.tr" + report_url
                
                response = requests.get(report_url, headers={"User-Agent": "Mozilla/5.0"})
                if response.status_code == 200:
                    tarih = datetime.now().strftime("%Y-%m-%d")
                    dosya_adi = f"Garanti_Gunluk_Ozeti_{tarih}.pdf"
                    with open(dosya_adi, "wb") as f:
                        f.write(response.content)
                    print(f"BAŞARILI: {dosya_adi} indirildi.")
                else:
                    print(f"Hata: Sunucu dosyayı vermedi.")
            else:
                print(f"Hata: '{target_title}' bulunamadı.")

        except Exception as e:
            print(f"Hata: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    download_specific_report()
