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
# 4. CANLI PİYASA VERİSİ (Yahoo Finance)
# ==========================================
def fetch_market_data():
    symbols = {
        "BIST-100": "XU100.IS",
        "BIST-30":  "XU030.IS",
        "USD/TL":   "USDTRY=X",
        "EUR/TL":   "EURTRY=X",
    }
    result = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    for name, symbol in symbols.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                meta = data["chart"]["result"][0]["meta"]
                price = meta.get("regularMarketPrice")
                prev  = meta.get("chartPreviousClose") or meta.get("previousClose")
                if price and prev and prev != 0:
                    change_pct = ((price - prev) / prev) * 100
                    result[name] = {
                        "value":  round(price, 2),
                        "change": round(change_pct, 2)
                    }
                    print(f"--- {name}: {price} ({change_pct:+.2f}%) ---")
                else:
                    result[name] = {"value": price, "change": None}
            else:
                print(f"!!! {name} Yahoo hatası: {resp.status_code}")
                result[name] = {"value": None, "change": None}
        except Exception as e:
            print(f"!!! {name} veri hatası: {e}")
            result[name] = {"value": None, "change": None}
        time.sleep(0.3)

    return result


def format_market_table(market_data, prev_market_data=None):
    lines = [
        "```",
        "| Enstrüman  | Değer     | Değişim  |",
        "|------------|-----------|----------|",
    ]
    for name, d in market_data.items():
        value = d.get("value")
        change = d.get("change")

        if change is None and prev_market_data and name in prev_market_data:
            prev_val = prev_market_data[name].get("value")
            if prev_val and value and prev_val != 0:
                change = round(((value - prev_val) / prev_val) * 100, 2)

        val_str    = f"{value:,.2f}".replace(",", ".") if value else "--"
        change_str = f"{change:+.2f}%" if change is not None else "--"
        lines.append(f"| {name:<10} | {val_str:<9} | {change_str:<8} |")

    lines.append("```")
    return "\n".join(lines)


# ==========================================
# 5. TACİRLER SABAH BÜLTENİ
# ==========================================
def fetch_tacirler_bulten(history, page):
    bugun_sayi = datetime.now().strftime("%d.%m.%Y")
    report_key = "SABAH_RAPORU"

    if history.get(f"{report_key}_LAST_DATE") == bugun_sayi:
        print(f"BİLGİ: Sabah raporu zaten bugün gönderilmiş.")
        return history

    print(f"--- Tacirler Bülten Sayfası Kontrol Ediliyor: {bugun_sayi} ---")

    try:
        page.goto("https://tacirler.com.tr/arastirma/gunluk-bulten",
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        # ── 1. ADIM: Liste sayfasında bugüne ait kartı bul ──
        # Kartın herhangi bir yerinde bugünün tarihi varsa ve
        # içinde gunluk-bulen linki varsa o linki al.
        # find_parent() yerine kart bazlı arama yapıyoruz —
        # böylece tarih kartın herhangi bir derinliğinde olsa da bulunur.
        bulten_link = None

        for card in soup.find_all(["article", "div", "li", "section"]):
            # Sadece direkt child elementleri değil tüm text'e bak
            card_text = card.get_text()
            if bugun_sayi not in card_text:
                continue
            # Bu kartın içinde gunluk-bulen linki var mı?
            for a_tag in card.find_all("a", href=True):
                href = a_tag.get("href", "")
                if "gunluk-bulen" in href:
                    bulten_link = "https://tacirler.com.tr" + href if href.startswith("/") else href
                    print(f"--- Bugünkü bülten linki bulundu: {bulten_link} ---")
                    break
            if bulten_link:
                break

        if not bulten_link:
            print(f"BİLGİ: {bugun_sayi} tarihli bülten henüz yayınlanmamış, sonraki çalışmada tekrar denenecek.")
            return history

        # ── 2. ADIM: Detay sayfasına git, PDF linkini bul ──
        page.goto(bulten_link, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        detay_html = page.content()
        detay_soup = BeautifulSoup(detay_html, "html.parser")

        # Tarih doğrulaması artık burada değil, liste sayfasında yapıldı.
        # Detay sayfasında sadece PDF linkini arıyoruz.
        pdf_url = None
        for a_tag in detay_soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            text = a_tag.get_text(strip=True).lower()
            if ".pdf" in href.lower() or "detaylı pdf" in text or "detayli pdf" in text:
                pdf_url = href if href.startswith("http") else "https://tacirler.com.tr" + href
                print(f"--- PDF linki bulundu: {pdf_url} ---")
                break

        if not pdf_url:
            print("!!! Detay sayfasında PDF linki bulunamadı.")
            return history

        # ── 3. ADIM: PDF indir ve oku ──
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        pdf_resp = requests.get(pdf_url, headers=headers, timeout=30)
        with open("temp_tacirler.pdf", "wb") as f:
            f.write(pdf_resp.content)

        with pdfplumber.open("temp_tacirler.pdf") as pdf:
            tam_metin = ""
            for p in pdf.pages:
                text = p.extract_text(layout=True) or ""
                tam_metin += text + "\n\n"

        # Gereksiz boşlukları temizle — layout=True çok whitespace üretiyor
        tam_metin = re.sub(r' {2,}', ' ', tam_metin)      # çoklu boşluk → tek boşluk
        tam_metin = re.sub(r'\n{3,}', '\n\n', tam_metin)  # çoklu satır → çift satır
        tam_metin = tam_metin.strip()

        print(f"--- PDF okundu: {len(pdf.pages)} sayfa, temizlenmiş {len(tam_metin)} karakter ---")
        print("=== İLK 1500 KARAKTER ===")
        print(tam_metin[:1500])

        # ── 4. ADIM: Piyasa verisi + AI analizi ──
        print("--- Canlı piyasa verisi çekiliyor ---")
        market_data = fetch_market_data()
        market_table = format_market_table(market_data)
        history["SABAH_MARKET_DATA"] = market_data

        analysis = get_ai_analysis_tacirler(tam_metin, history, report_key, market_table)

        if "ERROR" not in analysis:
            send_telegram(analysis)
            history[f"{report_key}_LAST_DATE"] = bugun_sayi
            history[f"{report_key}_SUMMARY"] = analysis[:3000]
            print(f"--- Sabah raporu TAMAMLANDI ---")
        else:
            print(f"!!! Sabah raporu Analiz Hatası: {analysis}")

    except Exception as e:
        print(f"!!! Tacirler Bülten Hatası: {e}")

    return history


# ==========================================
# 6. RAPOR ANALİZİ (GROK) — TACİRLER
# ==========================================
def get_ai_analysis_tacirler(metin, history, report_key, market_table=""):
    bugun = datetime.now().strftime("%d.%m.%Y")

    prev_sabah = history.get("SABAH_RAPORU_SUMMARY", "")
    prev_ogle  = history.get("OGLE_RAPORU_SUMMARY", "")

    karsilastirma = f"""
Dünkü sabah raporu özeti:
{prev_sabah[:1500] if prev_sabah else "Henüz yok."}

Dünkü öğle raporu özeti:
{prev_ogle[:1000] if prev_ogle else "Henüz yok."}
"""

    system = """Sen deneyimli bir finansal analistsin. Her sabah kullanıcıya piyasa özetini aktarıyorsun.
Doğal, akıcı Türkçe kullan. Sanki sabah kahveni içerken bir arkadaşına durumu anlatıyormuşsun gibi.
Resmi rapor dili yok. Zorlama geçişler yok. Kullanıcının yazdığı mesajlara benzer, sade bir dil.
Bölüm başlıkları kalın olsun ama girişe "Değerli yatırımcı" veya benzeri hiçbir şey yazma.
Kullanıcıya sormak için yazmıyorsun, ona anlatıyorsun."""

    user = f"""
{bugun} tarihli Tacirler Yatırım günlük bültenini analiz et. Aşağıdaki sırayla yaz:

🌅 *GÜNLÜK PİYASA ÖZETİ*
_{bugun}_

İlk satır olarak kısa ve net bir günaydın cümlesi yaz. Format tam olarak şöyle olsun:
"Günaydın. Bugün [o günün en önemli gelişmesi veya piyasa teması 1 cümlede]."
Örnek: "Günaydın. Bugün piyasalar Hürmüz gerginliğinin petrolü 100 doların üzerine taşımasıyla temkinli açılıyor."
Sadece 1-2 cümle. Kahve, beraber bakalım gibi ifadeler yok. Profesyonel ama doğal.

**Piyasalar**
Aşağıdaki tabloyu olduğu gibi koy, hiçbir şey ekleme, değiştirme, açıklama yapma:
{market_table}

**Güne Başlarken**
Bugünün ana hikayesi ne? Jeopolitik, faiz, küresel piyasalar — neyin belirleyici olduğunu 3-4 cümleyle anlat.
"Hürmüz'deki gerginlik devam ediyor, bu da petrolü 100 dolar civarında tutuyor ve risk iştahını baskılıyor" gibi doğal bir dille.

**Teknik Görünüm**
BIST-100 için rapordaki destek/direnç seviyelerini ver. VİOP varsa onu da ekle.
USD/TL ve EUR/TL için rapordaki teknik yorumu kısaca aktar — "45 seviyesi kritik, altında kalıcı düşüş zor görünüyor" gibi.
Günlük teknik analiz bazlı hisse önerilerini de buraya ekle — hangi hisseler alım aralığında, hangilerinde satım hedefi ne?

**Global Piyasalar ve Makro**
Rapordaki "Global Piyasalarda Öne Çıkanlar" ve "Ekonomi ve Politika Haberleri" bölümlerinden önemli olanları seç.
Her başlık için 1-2 cümle yeter — "Tüketici güveni nisanda 85,5'e çıktı, beklentiler kısmen toparlıyor ama mevcut durum algısı hâlâ zayıf" gibi.
Hepsini değil, gerçekten öne çıkanları al.

**Kısa Vadeli Beklenti**
Önümüzdeki 1-3 gün için ne bekleniyor? İyimser ve kötümser iki senaryo ver.
Hangi seviye veya gelişme belirleyici olur?

**Dünle Kıyasla**
{karsilastirma[:2000]}
Varsa karşılaştır — "Dünkü sabaha göre dolar biraz daha sertleşmiş, risk iştahı aynı kötü seyriyor" gibi doğal bir dille.
Veri yoksa bu bölümü atla, "henüz veri yok" yazma.

**Öne Çıkan Şirket Haberleri**
Rapordaki şirket haberlerinin hepsini değil, en çarpıcı 5-7 tanesini seç.
Hangisi önemli, hangisi yatırımcıyı etkiler — bunu sen karar ver.
Her biri için 1-2 cümle, doğal dille:
🟢 CWENE karını yıllık bazda neredeyse ikiye katladı, güçlü bir çeyrek geçirmiş.
🔴 SOKE net zararda, üstelik bir önceki çeyreğe göre de kötüleşmiş.
Olumlu/olumsuz/karışık — nasıl hissettiriyorsa öyle yaz, işaret tekrarlama.

BÜLTEN İÇERİĞİ:
{metin[:35000]}
"""

    print(f"--- Grok Tacirler Analizi Başlatılıyor ---")
    result = call_grok(system, user, max_tokens=8000)
    return result


# ==========================================
# 7. GÜN ORTASI RAPORU (GARANTİ BBVA)
# ==========================================
def get_ai_analysis_garanti(pdf_text, history, market_table=""):
    bugun = datetime.now().strftime("%d.%m.%Y")

    prev_sabah = history.get("SABAH_RAPORU_SUMMARY", "")
    prev_ogle  = history.get("OGLE_RAPORU_SUMMARY", "")

    karsilastirma = f"""
Bugünkü sabah raporu özeti:
{prev_sabah[:1500] if prev_sabah else "Henüz yok."}

Dünkü öğle raporu özeti:
{prev_ogle[:1000] if prev_ogle else "Henüz yok."}
"""

    system = """Sen deneyimli bir finansal analistsin. Kullanıcıya öğlen piyasa güncellemesini aktarıyorsun.
Dil profesyonel ama doğal olsun — ne çok resmi ne çok samimi.
Asla açıklama yapma: "tabloyu olduğu gibi bıraktım", "PDF'e sadık kaldım", "ellemedim" gibi ifadeler kesinlikle yasak.
Direkt içeriğe gir, metodoloji anlatma."""

    user = f"""
{bugun} tarihli Garanti BBVA gün ortası notlarını analiz et.

🕐 *GÜN ORTASI NOTLARI*
_{bugun}_

Başlıktan önce tek cümlelik bir giriş yaz. Format:
"Öğlen itibarıyla [o anki en önemli gelişme veya endeks durumu 1 cümlede]."
Örnek: "Öğlen itibarıyla endeks 14.200 civarında seyrediyor, sabahın temkinli havası devam ediyor."
Açıklama yapma, direkt gir.

**Piyasalar**
Aşağıdaki tabloyu olduğu gibi koy, hiçbir ekleme veya açıklama yapma:
{market_table}

**Gün İçinde Ne Oldu?**
Sabahtan bu yana ne değişti? 3-4 cümle yeter.
"Petrol 100 doların üzerine çıktı, bu endeksi baskılamaya devam ediyor" gibi doğal bir dille.
Açıklama yapma, direkt anlat.

**Teknik Seviyeler**
BIST-100 ve VİOP için destek/direnç — kısa ve net.

**Öne Çıkan Şirket Haberleri**
En çarpıcı 3-5 tanesini seç, hepsini yazma.
🟢 veya 🔴, 1-2 cümle, doğal dille. İşaret tekrarı yapma.

**Sabahla Kıyasla**
{karsilastirma[:2000]}
Varsa karşılaştır, yoksa bu bölümü atla. "Sabaha göre dolar biraz daha sertleşmiş..." gibi.

**Günün Geri Kalanı**
Kısa vadeli beklenti — yarım cümle bile yeter bazen.

PDF METNİ:
{pdf_text[:30000]}
"""

    print(f"--- Grok Garanti Öğle Analizi Başlatılıyor ---")
    return call_grok(system, user, max_tokens=8000)


def fetch_ogle_raporu(history, page):
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

        # Tüm olası kart selectorlarını dene
        items = page.query_selector_all(".reports-list-item, article, .report-item, .card, li")
        print(f"--- Sitede {len(items)} adet element bulundu ---")

        pdf_url = None
        for item in items:
            try:
                text = item.inner_text() or ""
            except:
                continue
            text_lower = text.lower()

            # Debug: her kartın ilk 80 karakterini logla
            print(f"KART: {text_lower[:80].strip()}")

            # Hem "gün ortası notları" hem bugünün tarihi aynı kartta olmalı
            if "gün ortası notları" not in text_lower:
                continue
            if bugun_sayi not in text and bugun_metin not in text_lower:
                continue

            print(f"--- EŞLEŞME: Gün ortası notları işleniyor ---")

            # PDF linkini bul — önce href'te .pdf ara, sonra "İndir" metinli link
            link_elem = (
                item.query_selector("a[href*='.pdf']") or
                item.query_selector("a[href*='indir']") or
                item.query_selector("a:has-text('İndir')") or
                item.query_selector("a.report-download")
            )
            if link_elem:
                pdf_url = link_elem.get_attribute("href")
                if pdf_url and not pdf_url.startswith("http"):
                    pdf_url = "https://www.garantibbvayatirim.com.tr" + pdf_url
                print(f"--- PDF linki bulundu: {pdf_url} ---")
                break
            else:
                print("!!! Kart bulundu ama PDF linki yok.")

        if not pdf_url:
            print(f"BİLGİ: Gün ortası notları için bugüne ait rapor bulunamadı.")
            return history

        # PDF indir ve oku
        resp = requests.get(pdf_url)
        with open("temp_ogle.pdf", "wb") as f:
            f.write(resp.content)

        with pdfplumber.open("temp_ogle.pdf") as pdf:
            raw_text = "".join(
                p.extract_text(layout=True) or ""
                for p in pdf.pages[:8]
            )

        # Gereksiz boşlukları temizle
        raw_text = re.sub(r' {2,}', ' ', raw_text)
        raw_text = re.sub(r'\n{3,}', '\n\n', raw_text)
        raw_text = raw_text.strip()

        print(f"=== ÖĞLE PDF (temizlenmiş {len(raw_text)} karakter) ===")
        print(raw_text[:1000])

        print("--- Öğle canlı piyasa verisi çekiliyor ---")
        market_data = fetch_market_data()
        sabah_data = history.get("SABAH_MARKET_DATA", {})
        for key in market_data:
            if market_data[key]["change"] is None and key in sabah_data:
                sabah_val = sabah_data[key].get("value")
                cur_val = market_data[key].get("value")
                if sabah_val and cur_val and sabah_val != 0:
                    market_data[key]["change"] = round(((cur_val - sabah_val) / sabah_val) * 100, 2)
        prev_ogle_data = history.get("OGLE_MARKET_DATA", {})
        market_table = format_market_table(market_data, prev_ogle_data)
        history["OGLE_MARKET_DATA"] = market_data

        time.sleep(3)
        analysis = get_ai_analysis_garanti(raw_text, history, market_table)

        if "ERROR" not in analysis:
            send_telegram(analysis)
            history[f"{report_key}_LAST_DATE"] = bugun_sayi
            history[f"{report_key}_SUMMARY"] = analysis[:3000]
            print(f"--- Öğle raporu TAMAMLANDI ---")
        else:
            print(f"!!! Öğle raporu Analiz Hatası: {analysis}")

    except Exception as e:
        print(f"!!! Garanti Öğle Raporu Hatası: {e}")

    return history


# ==========================================
# 8. HABER KAYNAKLARI
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
# 9. HABER ÇEKME
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
# 10. ÇAKIŞMA TESPİTİ + AI ÖZET
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
Kısa, net, doğal Türkçe yaz. ASLA giriş cümlesi yazma, açıklama yapma, metodoloji anlatma.
Direkt habere gir."""

    user = f"""
Aşağıdaki haberlere bak. Sadece piyasayı gerçekten etkileyen olumlu veya olumsuz olanları yaz.
Nötr/etkisiz haberleri atla. Giriş cümlesi yazma, direkt haberlere başla.

Her önemli haber için bu format:
🟢 veya 🔴 *Başlık*
1-2 cümle — ne oldu, piyasaya etkisi ne?
🔗 link

Birden fazla kaynakta geçen haberlerde "✅ X kaynak doğruluyor" ekle.
Hiç önemli haber yoksa sadece: YOK

Haberler:
{news_text}
"""
    print(f"--- {len(all_items)} haber ({len(groups)} grup) Grok'a gönderiliyor ---")
    return call_grok(system, user, max_tokens=2000)

# ==========================================
# 11. HABER MONİTÖRÜ
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
# 12. ANA OTOMASYON
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
