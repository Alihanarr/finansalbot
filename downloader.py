import os
import requests
import json
import re
import pdfplumber
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

GROK_API_KEY     = clean_env("GROK_API_KEY")
TELEGRAM_TOKEN   = clean_env("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = clean_env("TELEGRAM_CHAT_ID")

GROK_API_URL = "https://api.x.ai/v1/chat/completions"
GROK_MODEL   = "grok-3-mini"

# ==========================================
# 2. GROK API ÇAĞRISI
# ==========================================
def call_grok(system_prompt, user_prompt, max_tokens=4000):
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": GROK_MODEL,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt}
        ]
    }
    for attempt in range(4):
        try:
            resp = requests.post(GROK_API_URL, headers=headers, json=payload, timeout=120)
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            elif resp.status_code == 429:
                wait = 60 * (attempt + 1)
                print(f"Grok kota hatası, {wait}sn bekleniyor... ({attempt+1}/4)")
                time.sleep(wait)
            else:
                print(f"!!! Grok API Hatası: {resp.status_code} — {resp.text[:200]}")
                return f"ERROR_GROK: {resp.status_code}"
        except requests.exceptions.Timeout:
            wait = 30 * (attempt + 1)
            print(f"!!! Grok timeout, {wait}sn bekleniyor... ({attempt+1}/4)")
            time.sleep(wait)
        except Exception as e:
            print(f"!!! Grok bağlantı hatası: {e}")
            return f"ERROR_GROK: {e}"
    return "ERROR_GROK: max deneme aşıldı"

# ==========================================
# 3. TELEGRAM GÖNDERİMİ
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
                print(f"!!! Telegram Markdown Hatası ({resp.status_code}), düz metin deneniyor...")
                requests.post(api_url, json={"chat_id": TELEGRAM_CHAT_ID, "text": part}, timeout=30)
            else:
                print(f"--- Telegram Parça {idx+1}/{len(parts)} gönderildi ---")
        except Exception as e:
            print(f"!!! Telegram bağlantı hatası: {e}")
        time.sleep(2)

# ==========================================
# 4. TACİRLER SABAH BÜLTENİ
# ==========================================
def fetch_tacirler_bulten(history, page):
    """
    Tacirler günlük bülten sayfasından bugünkü bülteni çeker.
    HTML içeriğini doğrudan okur, PDF'e gerek yok.
    """
    bugun_sayi = datetime.now().strftime("%d.%m.%Y")
    report_key = "SABAH_RAPORU"

    # Bugün zaten gönderildiyse atla
    if history.get(f"{report_key}_LAST_DATE") == bugun_sayi:
        print(f"BİLGİ: Sabah raporu zaten bugün gönderilmiş.")
        return history

    print(f"--- Tacirler Bülten Sayfası Kontrol Ediliyor: {bugun_sayi} ---")

    try:
        page.goto("https://tacirler.com.tr/arastirma/gunluk-bulten", 
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # En üstteki bülten linkini bul
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        # Bülten listesindeki ilk makale linkini bul
        bulten_link = None
        bulten_tarih = None

        # Tarih ve link içeren kartları tara
        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            if "gunluk-bulen" in href or "gunluk-bulten" in href:
                # Tarih bilgisi için parent elementi kontrol et
                parent = a_tag.find_parent()
                parent_text = parent.get_text() if parent else ""

                # Bugünün tarihini farklı formatlarda ara
                gun = datetime.now().strftime('%d')
                ay_sayisal = datetime.now().strftime('%m')
                yil = datetime.now().strftime('%Y')

                aylar = {
                    "01":"Ocak","02":"Şubat","03":"Mart","04":"Nisan","05":"Mayıs",
                    "06":"Haziran","07":"Temmuz","08":"Ağustos","09":"Eylül",
                    "10":"Ekim","11":"Kasım","12":"Aralık"
                }
                bugun_metin = f"{gun}.{ay_sayisal}.{yil}"
                bugun_metin2 = f"{int(gun)} {aylar[ay_sayisal]} {yil}"

                if bugun_metin in parent_text or bugun_metin2 in parent_text or bugun_sayi in parent_text:
                    bulten_link = "https://tacirler.com.tr" + href if href.startswith("/") else href
                    bulten_tarih = bugun_sayi
                    print(f"--- Bugünkü bülten bulundu: {bulten_link} ---")
                    break

        # Bulunamadıysa ilk linki dene (tarih kontrolü sayfada olmayabilir)
        if not bulten_link:
            for a_tag in soup.find_all("a", href=True):
                href = a_tag.get("href", "")
                if "gunluk-bulen" in href and "arastirma" not in href:
                    bulten_link = "https://tacirler.com.tr" + href if href.startswith("/") else href
                    print(f"--- İlk bülten linki deneniyor: {bulten_link} ---")
                    break

        if not bulten_link:
            print("!!! Bülten linki bulunamadı.")
            return history

        # Bülten sayfasına git ve içeriği oku
        page.goto(bulten_link, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        bulten_html = page.content()
        bulten_soup = BeautifulSoup(bulten_html, "html.parser")

        # Tarih kontrolü — sayfadaki tarihi oku
        tarih_elem = bulten_soup.find("h2", class_=lambda c: c and "fw-700" in c)
        if tarih_elem:
            sayfa_tarih = tarih_elem.get_text(strip=True)
            print(f"--- Sayfadaki tarih: {sayfa_tarih} ---")
            # Bugünün tarihi değilse atla
            if bugun_sayi not in sayfa_tarih and bugun_sayi.replace(".", "") not in sayfa_tarih.replace(".", ""):
                print(f"BİLGİ: Bülten tarihi {sayfa_tarih}, bugün değil. Atlanıyor.")
                return history

        # İçerikleri çek
        sections = {}
        for section in bulten_soup.find_all("section"):
            baslik_elem = section.find("h2")
            baslik = baslik_elem.get_text(strip=True) if baslik_elem else "Diğer"
            icerik = section.get_text(separator="\n", strip=True)
            sections[baslik] = icerik

        # Piyasa verileri tablosunu da çek (PDF'deki gibi)
        piyasa_verisi = ""
        for elem in bulten_soup.find_all(["table", "div"], class_=lambda c: c and ("piyasa" in str(c).lower() or "table" in str(c).lower())):
            piyasa_verisi += elem.get_text(separator=" | ", strip=True) + "\n"

        # Tüm metni birleştir
        tam_metin = f"Tarih: {bugun_sayi}\n\n"
        for baslik, icerik in sections.items():
            tam_metin += f"=== {baslik} ===\n{icerik}\n\n"

        if piyasa_verisi:
            tam_metin = f"PİYASA VERİLERİ:\n{piyasa_verisi}\n\n" + tam_metin

        print(f"--- Bülten içeriği çekildi ({len(tam_metin)} karakter) ---")
        print("=== İLK 1500 KARAKTER ===")
        print(tam_metin[:1500])

        # AI analizi
        analysis = get_ai_analysis_tacirler(tam_metin, history, report_key)

        if "ERROR" not in analysis:
            send_telegram(analysis)
            history[f"{report_key}_LAST_DATE"] = bugun_sayi
            history[f"{report_key}_SUMMARY"] = analysis[:3000]  # özet olarak sakla
            print(f"--- Sabah raporu TAMAMLANDI ---")
        else:
            print(f"!!! Sabah raporu Analiz Hatası: {analysis}")

    except Exception as e:
        print(f"!!! Tacirler Bülten Hatası: {e}")

    return history

# ==========================================
# 5. RAPOR ANALİZİ (GROK) — TACİRLER
# ==========================================
def get_ai_analysis_tacirler(metin, history, report_key):
    bugun = datetime.now().strftime("%d.%m.%Y")

    prev_sabah = history.get("SABAH_RAPORU_SUMMARY", "")
    prev_ogle  = history.get("OGLE_RAPORU_SUMMARY", "")

    karsilastirma = f"""
Dünkü sabah raporu özeti:
{prev_sabah[:1500] if prev_sabah else "Henüz yok."}

Dünkü öğle raporu özeti:
{prev_ogle[:1000] if prev_ogle else "Henüz yok."}
"""

    system = """Sen deneyimli bir finansal analistsin. Kullanıcı seni her sabah piyasa özetini aktarmanı bekliyor.
Yazın samimi, akıcı ve doğal Türkçe olsun — sanki bir meslektaşın sana durumu anlatıyormuş gibi.
Resmi rapor dili kullanma. Zorlama kalıplardan kaçın. Kısa ve öz cümleler kur."""

    user = f"""
{bugun} tarihli Tacirler Yatırım sabah bültenini analiz et.

Şu bölümleri sırayla yaz:

🌅 *GÜNLÜK PİYASA ÖZETİ*
_{bugun}_

**Piyasalar**
Rapordaki piyasa verilerini tabloda göster. Sadece metinde geçen gerçek sayıları kullan.
```
| Enstrüman     | Değer      | Değişim |
|---------------|------------|---------|
| BIST-100      | ...        | ...     |
...
```

**Güne Başlarken**
Ana temayı 3-5 cümleyle anlat. Jeopolitik, faiz, risk iştahı — ne öne çıkıyorsa.
Doğal dille, "piyasalar şunu yapıyor, çünkü şu oluyor" mantığıyla.

**Teknik Seviyeler**
BIST-100 ve VİOP için destek/direnç kısa ve net.

**Şirket Haberleri**
Her şirket için ne oldu, neden önemli, kısa vadede ne beklenebilir?
Olumlu gelişmeler için 🟢, olumsuz için 🔴 kullan.
Doğal anlat — "CWENE bu çeyrekte karını ikiye katladı, güçlü büyüme devam ediyor..." gibi.

**Ekonomi Haberleri**
Önemli makro gelişmeleri kısaca özetle.

**Dünle Kıyasla**
{karsilastirma[:2000]}
Varsa karşılaştır, yoksa geç.
Kıyaslarken doğal konuş: "Dünkü sabaha göre dolar biraz daha yukarı..."

**Kısa Vadeli Beklenti**
Önümüzdeki 1-3 gün için sade yorum. İyimser/kötümser senaryo.
Dikkat edilmesi gereken seviye veya gelişme var mı?

BÜLTEN İÇERİĞİ:
{metin[:18000]}
"""

    print(f"--- Grok Tacirler Analizi Başlatılıyor ---")
    result = call_grok(system, user, max_tokens=6000)
    return result

# ==========================================
# 6. GÜN ORTASI RAPORU (GARANTİ BBVA)
# ==========================================
def get_ai_analysis_garanti(pdf_text, history):
    """Garanti gün ortası notları için Grok analizi."""
    bugun = datetime.now().strftime("%d.%m.%Y")

    prev_sabah = history.get("SABAH_RAPORU_SUMMARY", "")
    prev_ogle  = history.get("OGLE_RAPORU_SUMMARY", "")

    karsilastirma = f"""
Bugünkü sabah raporu özeti:
{prev_sabah[:1500] if prev_sabah else "Henüz yok."}

Dünkü öğle raporu özeti:
{prev_ogle[:1000] if prev_ogle else "Henüz yok."}
"""

    system = """Sen deneyimli bir finansal analistsin. Kullanıcı seni öğlen piyasa güncellemesini aktarmanı bekliyor.
Yazın samimi, akıcı ve doğal Türkçe olsun — sanki bir meslektaşın sana durumu anlatıyormuş gibi.
Resmi rapor dili kullanma. Zorlama kalıplardan kaçın."""

    user = f"""
{bugun} tarihli Garanti BBVA gün ortası notlarını analiz et.

Şu bölümleri sırayla yaz:

🕐 *GÜN ORTASI NOTLARI*
_{bugun}_

**Piyasalar**
PDF'deki gerçek sayıları kullan — tahmin yapma, üretme.
Bulamazsan o satırı tabloya ekleme.
```
| Enstrüman  | Değer | Değişim |
|------------|-------|---------|
...
```

**Gün İçinde Ne Oldu?**
Ana temayı 3-5 cümleyle anlat. Sabahtan bu yana ne değişti?
Doğal dille konuş.

**Teknik Seviyeler**
BIST-100 ve VİOP için destek/direnç kısa ve net.

**Şirket Haberleri**
Olumlu için 🟢, olumsuz için 🔴.
Her şirket için ne oldu, neden önemli, kısa vadede ne bekleniyor?
Doğal anlat, işaret tekrarı yapma.

**Sabahla Kıyasla**
{karsilastirma[:2000]}
Varsa karşılaştır — "Sabaha göre dolar biraz daha sertleşmiş..." gibi doğal dille.

**Kısa Vadeli Beklenti**
Günün geri kalanı ve yarın için sade yorum.

PDF METNİ:
{pdf_text[:18000]}
"""

    print(f"--- Grok Garanti Öğle Analizi Başlatılıyor ---")
    return call_grok(system, user, max_tokens=6000)


def fetch_ogle_raporu(history, page):
    """Garanti BBVA gün ortası notlarını çeker ve analiz eder."""
    bugun_sayi = datetime.now().strftime("%d.%m.%Y")
    report_key = "OGLE_RAPORU"

    if history.get(f"{report_key}_LAST_DATE") == bugun_sayi:
        print(f"BİLGİ: Öğle raporu zaten bugün gönderilmiş.")
        return history

    aylar = {
        "01":"Ocak","02":"Şubat","03":"Mart","04":"Nisan","05":"Mayıs","06":"Haziran",
        "07":"Temmuz","08":"Ağustos","09":"Eylül","10":"Ekim","11":"Kasım","12":"Aralık"
    }
    gun = datetime.now().strftime('%d').lstrip('0')
    bugun_metin = f"{gun} {aylar[datetime.now().strftime('%m')]}".lower()

    site_url = "https://www.garantibbvayatirim.com.tr/arastirma-raporlari"
    print(f"--- Garanti BBVA Gün Ortası Kontrol Ediliyor: {bugun_sayi} ---")

    try:
        page.goto(site_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(10000)

        items = page.query_selector_all(".reports-list-item")
        print(f"--- Sitede {len(items)} adet rapor bulundu ---")

        for item in items:
            text = item.inner_text().lower()
            if "gün ortası notları" in text and (bugun_sayi in text or bugun_metin in text):
                print(f"--- EŞLEŞME: Gün ortası notları işleniyor ---")
                link_elem = item.query_selector("a.report-download")
                if link_elem:
                    pdf_url = link_elem.get_attribute("href")
                    if not pdf_url.startswith("http"):
                        pdf_url = "https://www.garantibbvayatirim.com.tr" + pdf_url

                    resp = requests.get(pdf_url)
                    with open("temp_ogle.pdf", "wb") as f:
                        f.write(resp.content)

                    with pdfplumber.open("temp_ogle.pdf") as pdf:
                        raw_text = "".join(
                            p.extract_text(layout=True) or ""
                            for p in pdf.pages[:8]
                        )

                    print("=== ÖĞLE PDF (ilk 1000 karakter) ===")
                    print(raw_text[:1000])

                    time.sleep(3)
                    analysis = get_ai_analysis_garanti(raw_text, history)

                    if "ERROR" not in analysis:
                        send_telegram(analysis)
                        history[f"{report_key}_LAST_DATE"] = bugun_sayi
                        history[f"{report_key}_SUMMARY"] = analysis[:3000]
                        print(f"--- Öğle raporu TAMAMLANDI ---")
                    else:
                        print(f"!!! Öğle raporu Analiz Hatası: {analysis}")
                break
        else:
            print(f"BİLGİ: Gün ortası notları için bugüne ait rapor bulunamadı.")

    except Exception as e:
        print(f"!!! Garanti Öğle Raporu Hatası: {e}")

    return history

# ==========================================
# 7. HABER KAYNAKLARI
# ==========================================
NEWS_SOURCES = [
    {
        "name": "Bloomberg HT",
        "url": "https://www.bloomberght.com/haberler",
        "link_prefix": "https://www.bloomberght.com",
    },
    {
        "name": "Bloomberg HT Son Dakika",
        "url": "https://www.bloomberght.com/sondakika",
        "link_prefix": "https://www.bloomberght.com",
    },
    {
        "name": "Doviz.com Haberler",
        "url": "https://haber.doviz.com",
        "link_prefix": "https://haber.doviz.com",
    },
    {
        "name": "Ekonomim.com",
        "url": "https://www.ekonomim.com",
        "link_prefix": "https://www.ekonomim.com",
    },
    {
        "name": "Bigpara",
        "url": "https://bigpara.hurriyet.com.tr/haberler/",
        "link_prefix": "https://bigpara.hurriyet.com.tr",
    },
]

FINANCE_KEYWORDS = [
    "borsa", "bist", "hisse", "dolar", "euro", "faiz", "enflasyon",
    "merkez bankası", "tcmb", "fed", "piyasa", "altın", "ekonomi",
    "şirket", "kâr", "kar", "zarar", "ihracat", "ithalat", "büyüme",
    "döviz", "tahvil", "bono", "repo", "swap", "petrol", "endeks",
    "yatırım", "sermaye", "halka arz", "temettü", "bilanço", "bddk",
    "spk", "viop", "eurobond", "cds", "rezerv"
]

# ==========================================
# 8. HABER ÇEKME
# ==========================================
def fetch_news_from_source(source, seen_links):
    new_items = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "tr-TR,tr;q=0.9",
    }

    try:
        resp = requests.get(source["url"], headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"!!! {source['name']} erişim hatası: {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        all_links = soup.find_all("a", href=True)

        for a_tag in all_links:
            title = a_tag.get_text(strip=True)
            href = a_tag.get("href", "")

            if not href or not title or len(title) < 20 or len(title) > 200:
                continue

            if href.startswith("http"):
                full_url = href
            elif href.startswith("/"):
                full_url = source["link_prefix"] + href
            else:
                continue

            if source["link_prefix"].split("//")[1].split("/")[0] not in full_url:
                continue

            if full_url in seen_links:
                continue

            title_lower = title.lower()
            if not any(kw in title_lower for kw in FINANCE_KEYWORDS):
                continue

            new_items.append({
                "source": source["name"],
                "title": title,
                "url": full_url
            })
            seen_links.add(full_url)

        new_items = new_items[:15]
        print(f"--- {source['name']}: {len(new_items)} yeni haber ---")

    except Exception as e:
        print(f"!!! {source['name']} hata: {e}")

    return new_items

# ==========================================
# 9. ÇAKIŞMA TESPİTİ + AI ÖZET
# ==========================================
def find_duplicates_and_summarize(all_items):
    def similarity_score(t1, t2):
        words1 = set(t1.lower().split())
        words2 = set(t2.lower().split())
        stop_words = {"ve", "ile", "bu", "bir", "da", "de", "mi", "mı", "mu", "mü", "için", "olan", "oldu"}
        words1 -= stop_words
        words2 -= stop_words
        if not words1 or not words2:
            return 0
        return len(words1 & words2) / min(len(words1), len(words2))

    groups = []
    used = set()

    for i, item in enumerate(all_items):
        if i in used:
            continue
        group = [item]
        used.add(i)
        for j, other in enumerate(all_items):
            if j in used or i == j:
                continue
            if similarity_score(item["title"], other["title"]) > 0.5:
                group.append(other)
                used.add(j)
        groups.append(group)

    news_lines = []
    for group in groups:
        sources = list({g["source"] for g in group})
        source_str = f"[{', '.join(sources)}]"
        confirm_str = f" ✅ {len(sources)} kaynak" if len(sources) > 1 else ""
        news_lines.append(f"- {source_str}{confirm_str} {group[0]['title']} | {group[0]['url']}")

    news_text = "\n".join(news_lines)

    system = """Sen deneyimli bir finansal analistsin. Son dakika haberleri geliyor, hangisi piyasayı etkiler?
Kısa, net, doğal Türkçe yaz."""

    user = f"""
Bu haberlere bak, sadece piyasayı gerçekten etkileyen olumlu (+) veya olumsuz (-) olanları yaz.
Nötr/etkisiz haberleri atla.

Her önemli haber için:
🟢 veya 🔴 *Başlık*
Ne anlama geliyor, piyasaya etkisi ne? (1-2 cümle, doğal dille)
🔗 link

Birden fazla kaynakta geçen haberlerde: "✅ X kaynak doğruluyor" ekle.
Hiç önemli haber yoksa: YOK

Haberler:
{news_text}
"""
    print(f"--- {len(all_items)} haber ({len(groups)} grup) Grok'a gönderiliyor ---")
    return call_grok(system, user, max_tokens=2000)

# ==========================================
# 10. HABER MONİTÖRÜ
# ==========================================
def run_news_monitor(history):
    print("\n========== HABER MONİTÖRÜ BAŞLADI ==========")

    seen_links = set(history.get("SEEN_NEWS_LINKS", []))
    all_new_items = []

    for source in NEWS_SOURCES:
        items = fetch_news_from_source(source, seen_links)
        all_new_items.extend(items)
        time.sleep(1)

    if not all_new_items:
        print("--- Yeni haber yok, Telegram'a gönderilmedi ---")
        history["SEEN_NEWS_LINKS"] = list(seen_links)[-500:]
        return history

    print(f"--- Toplam {len(all_new_items)} yeni haber işleniyor ---")
    summary = find_duplicates_and_summarize(all_new_items)

    if summary and "YOK" not in summary and "ERROR" not in summary:
        now = datetime.now().strftime("%H:%M")
        message = f"📡 *SON DAKİKA* — {now}\n\n{summary}"
        send_telegram(message)
        print("--- Haber özeti Telegram'a gönderildi ---")
    else:
        print("--- Önemli haber yok ---")

    history["SEEN_NEWS_LINKS"] = list(seen_links)[-500:]
    return history

# ==========================================
# 11. ANA OTOMASYON
# ==========================================
def process_automation():
    history_file = "history.json"
    history = json.load(open(history_file)) if os.path.exists(history_file) else {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )

        try:
            # ---- SABAH BÜLTENİ (Tacirler) ----
            history = fetch_tacirler_bulten(history, page)

            # ---- GÜN ORTASI RAPORU ----
            history = fetch_ogle_raporu(history, page)

        except Exception as e:
            print(f"!!! KRİTİK HATA: {e}")
        finally:
            browser.close()

    # ---- HABER MONİTÖRÜ ----
    history = run_news_monitor(history)

    # History kaydet
    with open(history_file, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print("--- History kaydedildi ---")

if __name__ == "__main__":
    process_automation()
