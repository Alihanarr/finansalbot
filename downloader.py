import os
import requests
import json
import re
import pdfplumber
import google.generativeai as genai
from playwright.sync_api import sync_playwright
from datetime import datetime
from bs4 import BeautifulSoup
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
# 2. MESAJ GÖNDERİMİ
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
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": header + part,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
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
# 3. KRİTİK: = FİLTRESİ (KOD SEVİYESİNDE)
# ==========================================
def filter_neutral_items(text):
    """
    Satır satır tarar. Sadece (+) veya (-) içeren satırları tutar.
    (=) içeren satırlar tamamen çıkarılır.
    Bir haber birden fazla satıra yayılıyorsa bloğu birlikte atar.
    """
    lines = text.split("\n")
    filtered = []
    skip_block = False

    for line in lines:
        stripped = line.strip()

        # Yeni bir madde başlıyor mu? (- ile başlayan veya hisse kodu benzeri)
        is_new_item = stripped.startswith("-") or re.match(r'^[A-ZÇĞİÖŞÜ]{3,6}:', stripped)

        if is_new_item:
            # Bu maddenin işaretini kontrol et
            if "(=)" in stripped:
                skip_block = True   # Bu bloğu atla
            elif "(+)" in stripped or "(-)" in stripped:
                skip_block = False  # Bu bloğu göster
                filtered.append(line)
            else:
                skip_block = False  # İşaretsiz satırlar geçsin (başlıklar vs.)
                filtered.append(line)
        else:
            # Mevcut bloğun devamı
            if not skip_block:
                filtered.append(line)

    result = "\n".join(filtered)

    # Kaç madde atıldığını logla
    original_count = len(re.findall(r'\(=\)', text))
    print(f"--- Filtre: {original_count} adet (=) maddesi çıkarıldı ---")

    return result

# ==========================================
# 4. GEMİNİ ANALİZ MOTORU
# ==========================================
def get_ai_analysis(pdf_text, prev_sum, r_type):
    # Önce filtrele, sonra modele gönder
    pdf_text = filter_neutral_items(pdf_text)

    for attempt in range(3):
        try:
            print(f"--- Gemini 2.5 Flash Analizi Başlatılıyor... (Deneme {attempt+1}/3) ---")
            model = genai.GenerativeModel('gemini-2.5-flash')

            is_ogle = "gün ortası" in r_type.lower() or "ogle" in r_type.lower()
            display_title = "GÜN ORTASI NOTLARI ANALİZİ" if is_ogle else "GÜNLÜK PİYASA ÖZETİ ANALİZİ"

            if is_ogle:
                prompt = f"""
Sen kıdemli bir finansal analistsin. Bir İşletme Mühendisi ve SPL Düzey 1 sahibi profesyonel için analiz yap.

ÖNEMLİ: Sana gelen metin zaten filtrelenmiştir. Sadece (+) ve (-) işaretli gelişmeler var.
(=) işaretli (beklenti dahilinde) maddeler zaten çıkarılmıştır, bunları ekleme.

GÖRSEL KURALLAR:
1. Mesaja DOĞRUDAN şu başlıkla başla: **{display_title}**
2. Hemen altına italik: _{datetime.now().strftime("%d.%m.%Y")} tarihli rapor özeti_
3. Giriş nezaket cümleleri (Merhaba, Sayın vb.) ASLA KULLANMA.
4. Tüm piyasa verilerini ve tabloları ``` içine al, ASCII tablo formatında hizala.
5. Bölüm başlıklarını **KALIN** yaz.
6. Madde işaretlerinde * yerine - kullan.
7. En sona **📊 ÖNCEKİ RAPORLA KIYASLAMA** bölümü ekle.

ZORUNLU BÖLÜMLER:
**GENEL PİYASA GÖRÜNÜMÜ**
**PİYASA VERİLERİ TABLOSU** (``` içinde ASCII tablo)
**TEKNİK SEVİYELER**
**GÜNDEM VE ÖNE ÇIKAN GELİŞMELER** (sadece + ve - olanlar)
**📊 ÖNCEKİ RAPORLA KIYASLAMA**

ÖNCEKİ ÖZET: {prev_sum if prev_sum else "İlk analiz verisi."}
METİN: {pdf_text[:15000]}
"""
            else:
                prompt = f"""
Sen kıdemli bir finansal analistsin. Bir İşletme Mühendisi ve SPL Düzey 1 sahibi bir profesyonel için analiz yap.

ÖNEMLİ: Sana gelen metin zaten filtrelenmiştir. Sadece (+) ve (-) işaretli gelişmeler var.
(=) işaretli (beklenti dahilinde) maddeler zaten çıkarılmıştır, bunları ekleme.

GÖRSEL KURALLAR:
1. Mesaja doğrudan şu başlıkla başla: **{display_title}**
2. Hemen altına: _{datetime.now().strftime("%d.%m.%Y")} tarihli rapor özeti_
3. Giriş nezaket cümleleri ASLA KULLANMA.
4. TABLOLARI JİLET GİBİ YAP: ``` içinde ASCII formatında hizala.
5. Kritik haberleri **KALIN** başlıklarla ver.
6. **📊 TREND VE ÖNCEKİ RAPORLA KIYASLAMA**: En sonda analiz et.
7. VERİLERİ ASLA DEĞİŞTİRME.

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
# 5. HABER KAYNAKLARI TANIMI
# ==========================================
NEWS_SOURCES = [
    {
        "name": "Bloomberg HT",
        "url": "https://www.bloomberght.com/",
        "item_selector": "article, .news-item, .haber-item, .story",
        "title_selector": "h2, h3, .title, .baslik",
        "link_selector": "a",
        "link_prefix": "https://www.bloomberght.com",
    },
    {
        "name": "Investing.com TR",
        "url": "https://tr.investing.com/news/latest-news",
        "item_selector": ".articleItem, article.js-article-item",
        "title_selector": "a.title, .articleDetails h3",
        "link_selector": "a.title, a",
        "link_prefix": "https://tr.investing.com",
    },
    {
        "name": "Doviz.com",
        "url": "https://www.doviz.com/haberler/",
        "item_selector": ".news-list-item, .haber",
        "title_selector": "h2, h3, .title",
        "link_selector": "a",
        "link_prefix": "https://www.doviz.com",
    },
    {
        "name": "Para.com.tr",
        "url": "https://www.para.com.tr/haber/son-dakika/",
        "item_selector": ".news-card, .haber-item, article",
        "title_selector": "h2, h3, .card-title",
        "link_selector": "a",
        "link_prefix": "https://www.para.com.tr",
    },
    {
        "name": "Ekonomim.com",
        "url": "https://www.ekonomim.com/son-dakika",
        "item_selector": ".news-item, article, .haber",
        "title_selector": "h2, h3, .title",
        "link_selector": "a",
        "link_prefix": "https://www.ekonomim.com",
    },
]

# ==========================================
# 6. HABER ÇEKME VE FİLTRELEME
# ==========================================
def fetch_news_from_source(source, seen_links):
    """Bir kaynaktan yeni haberleri çeker."""
    new_items = []
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

    try:
        resp = requests.get(source["url"], headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"!!! {source['name']} erişim hatası: {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select(source["item_selector"])

        if not items:
            # Fallback: tüm linkleri tara
            items = soup.find_all("a", href=True)

        for item in items[:20]:  # İlk 20 haber yeterli
            # Başlığı bul
            title_elem = item.select_one(source["title_selector"]) if hasattr(item, 'select_one') else None
            title = title_elem.get_text(strip=True) if title_elem else item.get_text(strip=True)

            # Linki bul
            link_elem = item.select_one(source["link_selector"]) if hasattr(item, 'select_one') else item
            href = link_elem.get("href", "") if link_elem else ""

            if not href or not title or len(title) < 15:
                continue

            # Tam URL oluştur
            if href.startswith("http"):
                full_url = href
            elif href.startswith("/"):
                full_url = source["link_prefix"] + href
            else:
                continue

            # Daha önce görüldü mü?
            if full_url in seen_links:
                continue

            # Finans ile ilgili mi? (basit keyword filtresi)
            keywords = ["borsa", "bist", "hisse", "dolar", "euro", "faiz", "enflasyon",
                       "merkez bankası", "tcmb", "fed", "piyasa", "altın", "ekonomi",
                       "şirket", "kar", "zarar", "ihracat", "ithalat", "büyüme", "gdp"]
            title_lower = title.lower()
            if not any(kw in title_lower for kw in keywords):
                continue

            new_items.append({
                "source": source["name"],
                "title": title,
                "url": full_url
            })
            seen_links.add(full_url)

        print(f"--- {source['name']}: {len(new_items)} yeni haber bulundu ---")

    except Exception as e:
        print(f"!!! {source['name']} hata: {e}")

    return new_items

def summarize_news_with_ai(news_items):
    """Haberleri Gemini ile özetler ve piyasa etkisini değerlendirir."""
    if not news_items:
        return None

    news_text = "\n".join([
        f"- [{item['source']}] {item['title']} | {item['url']}"
        for item in news_items
    ])

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"""
Sen kıdemli bir finansal analistsin. Aşağıdaki son dakika haberlerini değerlendir.

Her haber için:
1. Piyasa etkisini belirle: (+) olumlu, (-) olumsuz, (=) nötr
2. (=) haberleri ATLA, sadece (+) ve (-) olanları yaz
3. 1-2 cümle özet yaz
4. Haberin linkini ekle

FORMAT (kesinlikle bu şekilde):
🔴 veya 🟢 **[KAYNAK] BAŞLIK** (+ veya -)
Özet: ...kısa açıklama...
🔗 link

Eğer hiç önemli haber yoksa sadece şunu yaz: "Yeni önemli gelişme yok."

HABERLer:
{news_text}
"""
        response = model.generate_content(prompt)
        return response.text

    except Exception as e:
        print(f"!!! Haber özet hatası: {e}")
        return None

def run_news_monitor(history):
    """Tüm kaynakları tarar, yeni önemli haberleri Telegram'a gönderir."""
    print("\n========== HABER MONİTÖRÜ BAŞLADI ==========")

    seen_links = set(history.get("SEEN_NEWS_LINKS", []))
    all_new_items = []

    for source in NEWS_SOURCES:
        items = fetch_news_from_source(source, seen_links)
        all_new_items.extend(items)
        time.sleep(1)  # Kaynaklara karşı nazik ol

    if not all_new_items:
        print("--- Yeni haber yok ---")
        history["SEEN_NEWS_LINKS"] = list(seen_links)
        return history

    print(f"--- Toplam {len(all_new_items)} yeni haber AI'ya gönderiliyor ---")
    summary = summarize_news_with_ai(all_new_items)

    if summary and "Yeni önemli gelişme yok" not in summary:
        now = datetime.now().strftime("%H:%M")
        message = f"📡 *SON DAKİKA HABER ÖZETİ* — {now}\n\n{summary}"
        send_telegram(message)
        print("--- Haber özeti Telegram'a gönderildi ---")
    else:
        print("--- Önemli haber yok, Telegram'a gönderilmedi ---")

    # Görülen linkleri kaydet (max 500 tutarak bellek şişmesini önle)
    history["SEEN_NEWS_LINKS"] = list(seen_links)[-500:]
    return history

# ==========================================
# 7. ANA OTOMASYON
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

    # ---- RAPOR MODÜLÜ (mevcut) ----
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
                                with open("temp.pdf", "wb") as f:
                                    f.write(resp.content)

                                with pdfplumber.open("temp.pdf") as pdf:
                                    raw_text = "".join(
                                        p.extract_text(layout=True) or ""
                                        for p in pdf.pages[:5]
                                    )

                                print("=== HAM PDF METNİ (ilk 1000 karakter) ===")
                                print(raw_text[:1000])

                                time.sleep(3)
                                analysis = get_ai_analysis(
                                    raw_text,
                                    history.get(f"{report_key}_SUMMARY", ""),
                                    target_title
                                )

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
            browser.close()

    # ---- HABER MONİTÖRÜ ----
    history = run_news_monitor(history)

    # History'yi kaydet
    with open(history_file, "w") as f:
        json.dump(history, f)

if __name__ == "__main__":
    process_automation()
