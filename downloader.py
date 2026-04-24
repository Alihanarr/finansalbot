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
# 4. (=) FİLTRESİ — KOD SEVİYESİNDE
# ==========================================
def filter_neutral_items(text):
    """
    Şirket/haber satırlarında (=) olanları atar, (+) ve (-) olanları tutar.
    Çok satırlı blokları birlikte işler.
    """
    lines = text.split("\n")
    filtered = []
    skip_block = False

    for line in lines:
        stripped = line.strip()
        # Yeni bir madde başlıyor mu? (hisse kodu veya - ile başlayan)
        is_new_item = bool(re.match(r'^[A-ZÇĞİÖŞÜ]{3,6}[\s:]', stripped)) or stripped.startswith("-")

        if is_new_item:
            if "(=)" in stripped:
                skip_block = True
            elif "(+)" in stripped or "(-)" in stripped:
                skip_block = False
                filtered.append(line)
            else:
                skip_block = False
                filtered.append(line)
        else:
            if not skip_block:
                filtered.append(line)

    removed = len(re.findall(r'\(=\)', text))
    print(f"--- Filtre: {removed} adet (=) maddesi çıkarıldı ---")
    return "\n".join(filtered)

# ==========================================
# 5. RAPOR ANALİZİ (GROK)
# ==========================================
def get_ai_analysis(pdf_text, history, report_key, r_type):
    pdf_text_filtered = filter_neutral_items(pdf_text)

    is_ogle = "gün ortası" in r_type.lower() or "ogle" in r_type.lower()
    display_title = "GÜN ORTASI NOTLARI ANALİZİ" if is_ogle else "GÜNLÜK PİYASA ÖZETİ ANALİZİ"
    bugun = datetime.now().strftime("%d.%m.%Y")

    # Kıyaslama geçmişlerini hazırla
    if is_ogle:
        prev_same   = history.get("OGLE_RAPORU_SUMMARY", "")      # dünkü öğle
        prev_other  = history.get("SABAH_RAPORU_SUMMARY", "")     # bugünkü sabah
        karsilastirma = f"""
ÖNCEKİ ÖĞLE RAPORU (dünkü): {prev_same if prev_same else "Henüz yok."}
BUGÜNKÜ SABAH RAPORU: {prev_other if prev_other else "Henüz yok."}
"""
    else:
        prev_same   = history.get("SABAH_RAPORU_SUMMARY", "")     # dünkü sabah
        prev_other  = history.get("OGLE_RAPORU_SUMMARY", "")      # dünkü öğle
        karsilastirma = f"""
ÖNCEKİ SABAH RAPORU (dünkü): {prev_same if prev_same else "Henüz yok."}
ÖNCEKİ ÖĞLE RAPORU (dünkü): {prev_other if prev_other else "Henüz yok."}
"""

    system = "Sen kıdemli bir finansal analistsin. Bir İşletme Mühendisi ve SPL Düzey 1 sahibi profesyonel için analiz yapıyorsun. Türkçe yazıyorsun."

    user = f"""
Aşağıdaki finansal raporu analiz et.

KRİTİK KURALLAR:
1. PDF'deki sayıları OLDUĞU GİBİ kullan. Asla tahmin yapma, yuvarlama yapma, eski veriden üretme.
   Dolar kuru, BIST, altın gibi veriler PDF'de ne yazıyorsa onu yaz.
2. (=) işaretli şirket/haber maddeleri zaten çıkarıldı. Bunları ekleme.
3. (+) ve (-) işaretli şirket haberlerini MUTLAKA dahil et ve neden önemli olduğunu açıkla.
4. Rapor detaylı olsun — her bölümü doldur, kısa kesme.

FORMAT KURALLARI:
- Mesaja DOĞRUDAN şu başlıkla başla: **{display_title}**
- Hemen altına: _{bugun} tarihli rapor özeti_
- Nezaket cümleleri (Merhaba, Sayın vb.) ASLA kullanma
- Tüm sayısal verileri ``` içinde ASCII tablo olarak ver ( | ve --- kullan)
- Bölüm başlıkları **KALIN**, maddeler - ile başlasın

ZORUNLU BÖLÜMLER (hepsini doldur, kısa kesme):

**GENEL PİYASA GÖRÜNÜMÜ**
Piyasanın genel seyri, öne çıkan tema ve riskler hakkında 3-5 cümle.

**PİYASA VERİLERİ TABLOSU**
PDF'deki güncel rakamlarla ASCII tablo. Mutlaka: BIST-100, USD/TL, EUR/TL, Altın, Petrol (varsa).

**TEKNİK SEVİYELER**
BIST-100 ve diğer enstrümanlar için destek/direnç seviyeleri, trend yorumu.

**SEKTÖR VE ŞİRKET HABERLERİ — SADECE (+) ve (-)**
Her madde için:
- 🟢(+) veya 🔴(-) [HİSSE KODU]: Gelişme ne? Neden önemli? Kısa vadeli etkisi ne olabilir?

**📊 ÖNCEKİ RAPORLARLA KIYASLAMA**
{karsilastirma[:2000]}
- Dünkü/önceki rapora göre ne değişti? (piyasa verileri, risk algısı, öne çıkan temalar)
- Öğle raporu için: sabah raporuna göre gün içinde ne değişti?

**🔮 KISA VADELİ AI YORUMU**
Bu gelişmeler ışığında önümüzdeki 1-3 gün için:
- Olası senaryolar (iyimser/kötümser)
- Dikkat edilmesi gereken seviyeler ve gelişmeler
- Genel pozisyon tavsiyesi (agresif değil, bilgilendirici)

METİN:
{pdf_text_filtered[:18000]}
"""

    print(f"--- Grok Rapor Analizi Başlatılıyor ({r_type}) ---")
    result = call_grok(system, user, max_tokens=6000)
    return result

# ==========================================
# 6. HABER KAYNAKLARI
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
    "spk", "viop", "eurobond", "cds", "rezerv", "enflasyon", "büyüme"
]

# ==========================================
# 7. HABER ÇEKME
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
# 8. ÇAKIŞMA TESPİTİ + AI ÖZET
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
        confirm_str = f" ✅ {len(sources)} kaynak onaylıyor" if len(sources) > 1 else ""
        news_lines.append(f"- {source_str}{confirm_str} {group[0]['title']} | {group[0]['url']}")

    news_text = "\n".join(news_lines)

    system = "Sen kıdemli bir finansal analistsin. Türkçe yazıyorsun."
    user = f"""
Aşağıdaki son dakika haberlerini değerlendir.

KURALLAR:
1. Her haber için piyasa etkisini belirle: (+) olumlu, (-) olumsuz
2. Nötr/etkisiz haberleri ATLA
3. Her önemli haber için format:
   🟢 veya 🔴 *[KAYNAK(LAR)] BAŞLIK*
   📝 Özet: 1-2 cümle — ne oldu ve piyasaya etkisi ne?
   🔗 link

4. Birden fazla kaynakta geçen haberlerde "✅ X kaynak onaylıyor" ifadesini koru
5. Hiç önemli haber yoksa sadece yaz: YOK

HABERLer:
{news_text}
"""
    print(f"--- {len(all_items)} haber ({len(groups)} grup) Grok'a gönderiliyor ---")
    return call_grok(system, user, max_tokens=2000)

# ==========================================
# 9. HABER MONİTÖRÜ
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
# 10. ANA OTOMASYON
# ==========================================
def process_automation():
    targets = {"günlük piyasa özeti": "SABAH_RAPORU", "gün ortası notları": "OGLE_RAPORU"}
    bugun_sayi = datetime.now().strftime("%d.%m.%Y")

    aylar = {
        "01":"Ocak","02":"Şubat","03":"Mart","04":"Nisan","05":"Mayıs","06":"Haziran",
        "07":"Temmuz","08":"Ağustos","09":"Eylül","10":"Ekim","11":"Kasım","12":"Aralık"
    }
    gun = datetime.now().strftime('%d').lstrip('0')
    bugun_metin = f"{gun} {aylar[datetime.now().strftime('%m')]}".lower()

    history_file = "history.json"
    history = json.load(open(history_file)) if os.path.exists(history_file) else {}

    # ---- RAPOR MODÜLÜ (Garanti BBVA) ----
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
        site_url = "https://www.garantibbvayatirim.com.tr/arastirma-raporlari"
        print(f"--- Garanti BBVA Siteye Gidiliyor: {bugun_sayi} ---")

        try:
            page.goto(site_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(10000)

            items = page.query_selector_all(".reports-list-item")
            print(f"--- Sitede {len(items)} adet rapor bulundu ---")

            for target_title, report_key in targets.items():
                found = False
                for item in items:
                    text = item.inner_text().lower()
                    if target_title in text and (bugun_sayi in text or bugun_metin in text):
                        found = True
                        if history.get(f"{report_key}_LAST_DATE") != bugun_sayi:
                            print(f"--- EŞLEŞME: {target_title} işleniyor ---")
                            link_elem = item.query_selector("a.report-download")
                            if link_elem:
                                pdf_url = link_elem.get_attribute("href")
                                if not pdf_url.startswith("http"):
                                    pdf_url = "https://www.garantibbvayatirim.com.tr" + pdf_url

                                resp = requests.get(pdf_url)
                                with open("temp.pdf", "wb") as f:
                                    f.write(resp.content)

                                with pdfplumber.open("temp.pdf") as pdf:
                                    raw_text = "".join(
                                        p.extract_text(layout=True) or ""
                                        for p in pdf.pages[:8]  # 5'ten 8'e çıkardık
                                    )

                                print("=== HAM PDF (ilk 1000 karakter) ===")
                                print(raw_text[:1000])

                                time.sleep(3)
                                analysis = get_ai_analysis(
                                    raw_text,
                                    history,
                                    report_key,
                                    target_title
                                )

                                if "ERROR" not in analysis:
                                    send_telegram(analysis)
                                    history[f"{report_key}_LAST_DATE"] = bugun_sayi
                                    history[f"{report_key}_SUMMARY"] = analysis
                                    print(f"--- {target_title} TAMAMLANDI ---")
                                else:
                                    print(f"!!! {target_title} Analiz Hatası: {analysis}")
                        else:
                            print(f"BİLGİ: {target_title} zaten bugün gönderilmiş.")
                        break

                if not found:
                    print(f"BİLGİ: {target_title} için bugüne ait rapor bulunamadı.")

        except Exception as e:
            print(f"!!! KRİTİK HATA (Rapor Modülü): {e}")
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
