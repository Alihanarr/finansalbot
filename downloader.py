import os
import requests
import json
import pdfplumber
import google.generativeai as genai
from playwright.sync_api import sync_playwright
from datetime import datetime
import time

# ==========================================
# 1. GÜVENLİ YAPILANDIRMA
# ==========================================
def clean_env(key):
    val = os.environ.get(key, "")
    return str(val).strip().replace("[", "").replace("]", "").replace("'", "").replace('"', "")

genai.configure(api_key=clean_env("GEMINI_API_KEY"))
TELEGRAM_TOKEN = clean_env("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = clean_env("TELEGRAM_CHAT_ID")

# ==========================================
# 2. MESAJ GÖNDERİMİ (ESTETİK NUMARALANDIRMA)
# ==========================================
def send_telegram(message):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    limit = 4000

    message = message.replace("### ", "**").replace("## ", "**").replace("# ", "**")
    message = "\n".join(
        "- " + line[2:] if line.startswith("* ") else line
        for line in message.split("\n")
    )

    parts = [message[i:i+limit] for i in range(0, len(message), limit)]

    for idx, part in enumerate(parts):
        header = f"*(Devamı {idx+1}/{len(parts)})*\n\n" if idx > 0 else ""
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": header + part, "parse_mode": "Markdown"}
        try:
            resp = requests.post(api_url, json=payload, timeout=30)
            if resp.status_code != 200:
                print(f"!!! Telegram Markdown Hatası (Kod: {resp.status_code}), Düz Metin Deneniyor...")
                requests.post(api_url, json={"chat_id": TELEGRAM_CHAT_ID, "text": part}, timeout=30)
            else:
                print(f"--- Telegram Parça {idx+1} Gönderildi ---")
        except Exception as e:
            print(f"!!! Telegram Bağlantı Hatası: {e}")
        time.sleep(2)

# ==========================================
# 3. GEMİNİ 2.5 ANALİZ MOTORU (MAX KALİTE)
# ==========================================
def get_ai_analysis(pdf_text, prev_sum, r_type):
    for attempt in range(3):
        try:
            print(f"--- Gemini 2.5 Flash Analizi Başlatılıyor... (Deneme {attempt+1}/3) ---")
            model = genai.GenerativeModel('gemini-2.5-flash')

            is_ogle = "gün ortası" in r_type.lower() or "ogle" in r_type.lower()
            display_title = "GÜN ORTASI NOTLARI ANALİZİ" if is_ogle else "GÜNLÜK PIYASA ÖZETİ ANALİZİ"

            if is_ogle:
                prompt = f"""
Sen kıdemli bir finansal analistsin. Bir İşletme Mühendisi ve SPL Düzey 1 sahibi profesyonel için analiz yap.

GÖRSEL KURALLAR — BUNLARA TAM UY:
1. Mesaja DOĞRUDAN şu başlıkla başla: **{display_title}**
2. Hemen altına italik: _{datetime.now().strftime("%d.%m.%Y")} tarihli rapor özeti_
3. Giriş nezaket cümleleri (Merhaba, Sayın vb.) ASLA KULLANMA.
4. Tüm piyasa verilerini ve tabloları ``` (üç ters tırnak) içine al, ASCII tablo formatında ( | ve --- ile) hizala.
5. Tablolarda sütunları düzgün hizala — her satır aynı genişlikte olsun.
6. Bölüm başlıklarını **KALIN** yaz.
7. Madde işaretlerinde * yerine - kullan (Telegram uyumu için).
8. Senaryolar varsa her birini ayrı satırda, - ile listele, iç içe girinti kullanma.
9. En sona **📊 ÖNCEKİ RAPORLA KIYASLAMA** bölümü ekle.

ZORUNLU BÖLÜMLER (bu sırayla):
**GENEL PİYASA GÖRÜNÜMÜ**
**PİYASA VERİLERİ TABLOSU** (``` içinde ASCII tablo)
**TEKNİK SEVİYELER** (BIST100, VİOP varsa)
**GÜNDEM VE ÖNE ÇIKAN GELİŞMELER**
**📊 ÖNCEKİ RAPORLA KIYASLAMA**

ÖNCEKİ ÖZET: {prev_sum if prev_sum else "İlk analiz verisi."}
METİN: {pdf_text[:15000]}
"""
            else:
                prompt = f"""
Sen kıdemli bir finansal analistsin. Bir İşletme Mühendisi ve SPL Düzey 1 sahibi bir profesyonel için analiz yap.

GÖRSEL KURALLAR:
1. Mesaja doğrudan şu başlıkla başla: **{display_title}**
2. Hemen altına: _{datetime.now().strftime("%d.%m.%Y")} tarihli rapor özeti_
3. Giriş nezaket cümleleri (Merhaba, Sayın vb.) ASLA KULLANMA.
4. TABLOLARI JİLET GİBİ YAP: Tüm piyasa verilerini ``` (üç ters tırnak) içine al ve ASCII formatında ( | ve --- kullanarak) hizala.
5. Kritik haberleri **KALIN** başlıklarla ver.
6. **📊 TREND VE ÖNCEKİ RAPORLA KIYASLAMA**: En sonda dünkü/sabahki farkları analiz et.
7. VERİLERİ ASLA DEĞİŞTİRME: PDF'deki sayıları olduğu gibi kullan, yuvarlama veya tahmin yapma.

ÖNCEKİ ÖZET: {prev_sum if prev_sum else "İlk analiz verisi."}
METİN: {pdf_text[:15000]}
"""

            response = model.generate_content(prompt)
            return response.text

        except Exception as e:
            if "429" in str(e) and attempt < 2:
                print(f"Kota hatası, 60sn bekleniyor... ({attempt+1}/3)")
                time.sleep(60)
            else:
                error_msg = f"ERROR_GEMINI: {str(e)}"
                print(f"!!! {error_msg}")
                return error_msg

# ==========================================
# 4. ANA OTOMASYON
# ==========================================
def process_automation():
    targets = {"günlük piyasa özeti": "SABAH_RAPORU", "gün ortası notları": "OGLE_RAPORU"}
    bugun_sayi = datetime.now().strftime("%d.%m.%Y")

    aylar = {"01":"Ocak","02":"Şubat","03":"Mart","04":"Nisan","05":"Mayıs","06":"Haziran",
             "07":"Temmuz","08":"Ağustos","09":"Eylül","10":"Ekim","11":"Kasım","12":"Aralık"}
    gun = datetime.now().strftime('%d').lstrip('0')
    bugun_metin = f"{gun} {aylar[datetime.now().strftime('%m')]}".lower()

    history_file = "history.json"
    history = json.load(open(history_file)) if os.path.exists(history_file) else {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")

        site_url = "https://www.garantibbvayatirim.com.tr/arastirma-raporlari"
        print(f"--- 1. Siteye Gidiliyor: {bugun_sayi} ---")

        try:
            page.goto(site_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(10000)

            items = page.query_selector_all(".reports-list-item")
            print(f"--- 2. Sitede {len(items)} adet rapor bulundu. ---")

            for target_title, report_key in targets.items():
                found = False
                for item in items:
                    text = item.inner_text().lower()
                    if target_title in text and (bugun_sayi in text or bugun_metin in text):
                        found = True
                        if history.get(f"{report_key}_LAST_DATE") != bugun_sayi:
                            print(f"--- 3. EŞLEŞME BULDUM: {target_title} İşleniyor... ---")
                            link_elem = item.query_selector("a.report-download")
                            if link_elem:
                                pdf_url = link_elem.get_attribute("href")
                                if not pdf_url.startswith("http"):
                                    pdf_url = "https://www.garantibbvayatirim.com.tr" + pdf_url

                                print(f"İndiriliyor: {pdf_url}")
                                resp = requests.get(pdf_url)
                                with open("temp.pdf", "wb") as f: f.write(resp.content)

                                with pdfplumber.open("temp.pdf") as pdf:
                                    raw_text = "".join(
                                        p.extract_text(layout=True) or ""
                                        for p in pdf.pages[:5]
                                    )

                                print("=== HAM PDF METNİ ===")
                                print(raw_text[:3000])

                                time.sleep(3)
                                analysis = get_ai_analysis(raw_text, history.get(f"{report_key}_SUMMARY", ""), target_title)

                                if "ERROR" not in analysis:
                                    send_telegram(analysis)
                                    history[f"{report_key}_LAST_DATE"] = bugun_sayi
                                    history[f"{report_key}_SUMMARY"] = analysis
                                    print(f"--- 4. {target_title} BAŞARIYLA TAMAMLANDI ---")
                                else:
                                    print(f"!!! {target_title} Analiz Hatası: {analysis}")
                        else:
                            print(f"BİLGİ: {target_title} zaten bugün gönderilmiş.")
                        break
                if not found:
                    print(f"BİLGİ: {target_title} için bugüne ait rapor listede görülmedi.")

        except Exception as e:
            print(f"!!! KRİTİK SİSTEM HATASI: {e}")
        finally:
            with open(history_file, "w") as f:
                json.dump(history, f)
            browser.close()

if __name__ == "__main__":
    process_automation()
