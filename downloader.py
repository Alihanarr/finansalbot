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
    for attempt in range(3):
        try:
            resp = requests.post(GROK_API_URL, headers=headers, json=payload, timeout=60)
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            elif resp.status_code == 429:
                print(f"Grok kota hatası, 60sn bekleniyor... ({attempt+1}/3)")
                time.sleep(60)
            else:
                print(f"!!! Grok API Hatası: {resp.status_code} — {resp.text[:200]}")
                return f"ERROR_GROK: {resp.status_code}"
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
    lines = text.split("\n")
    filtered = []
    skip_block = False

    for line in lines:
        stripped = line.strip()
        is_new_item = stripped.startswith("-") or re.match(r'^[A-ZÇĞİÖŞÜ]{3,6}[:\s]', stripped)

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
def get_ai_analysis(pdf_text, prev_sum, r_type):
    pdf_text = filter_neutral_items(pdf_text)

    is_ogle = "gün ortası" in r_type.lower() or "ogle" in r_type.lower()
    display_title = "GÜN ORTASI NOTLARI ANALİZİ" if is_ogle else "GÜNLÜK PİYASA ÖZETİ ANALİZİ"

    system = "Sen kıdemli bir finansal analistsin. Bir İşletme Mühendisi ve SPL Düzey 1 sahibi profesyonel için analiz yapıyorsun."

    user = f"""
ÖNEMLİ: Sana gelen metin zaten filtrelenmiştir. Sadece (+) ve (-) işaretli gelişmeler var.
(=) işaretli maddeler çıkarılmıştır, bunları kesinlikle ekleme.

GÖRSEL KURALLAR:
1. Mesaja DOĞRUDAN şu başlıkla başla: **{display_title}**
2. Hemen altına italik: _{datetime.now().strftime("%d.%m.%Y")} tarihli rapor özeti_
3. Giriş nezaket cümleleri (Merhaba, Sayın vb.) ASLA KULLANMA.
4. Tüm piyasa verilerini ``` içine al, ASCII tablo formatında ( | ve --- ile) hizala.
5. Bölüm başlıklarını **KALIN** yaz. Madde işaretinde * yerine - kullan.
6. En sona **📊 ÖNCEKİ RAPORLA KIYASLAMA** ekle.

ZORUNLU BÖLÜMLER:
**GENEL PİYASA GÖRÜNÜMÜ**
**PİYASA VERİLERİ TABLOSU**
**TEKNİK SEVİYELER**
**GÜNDEM — SADECE (+) ve (-) GELİŞMELER**
**📊 ÖNCEKİ RAPORLA KIYASLAMA**

ÖNCEKİ ÖZET: {prev_sum if prev_sum else "İlk analiz."}
METİN: {pdf_text[:15000]}
"""
    print(f"--- Grok Rapor Analizi Başlatılıyor ({r_type}) ---")
    result = call_grok(system, user)
    return result

# ==========================================
# 6. HABER KAYNAKLARI
# ==========================================
NEWS_SOURCES = [
    {
        "name": "Bloomberg HT",
        "url": "https://www.bloomberght.com/son-dakika",
        "item_selector": "article, .news-item, .haber-item, .liste-item",
        "title_selector": "h2, h3, .title, .baslik, a",
        "link_prefix": "https://www.bloomberght.com",
    },
    {
        "name": "Investing.com TR",
        "url": "https://tr.investing.com/news/latest-news",
        "item_selector": ".articleItem, article.js-article-item, .largeTitle",
        "title_selector": "a.title, .articleDetails h3, a",
        "link_prefix": "https://tr.investing.com",
    },
    {
        "name": "Doviz.com",
        "url": "https://www.doviz.com/haberler/son-dakika/",
        "item_selector": ".news-list-item, .haber-item, article",
        "title_selector": "h2, h3, .title, a",
        "link_prefix": "https://www.doviz.com",
    },
    {
        "name": "Para.com.tr",
        "url": "https://www.para.com.tr/haber/son-dakika/",
        "item_selector": ".news-card, .haber-item, article, .card",
        "title_selector": "h2, h3, .card-title, a",
        "link_prefix": "https://www.para.com.tr",
    },
    {
        "name": "Ekonomim.com",
        "url": "https://www.ekonomim.com/son-dakika",
        "item_selector": ".news-item, article, .haber, .list-item",
        "title_selector": "h2, h3, .title, a",
        "link_prefix": "https://www.ekonomim.com",
    },
]

FINANCE_KEYWORDS = [
    "borsa", "bist", "hisse", "dolar", "euro", "faiz", "enflasyon",
    "merkez bankası", "tcmb", "fed", "piyasa", "altın", "ekonomi",
    "şirket", "kâr", "zarar", "ihracat", "ithalat", "büyüme", "gdp",
    "döviz", "tahvil", "bono", "repo", "swap", "petrol", "endeks",
    "yatırım", "sermaye", "halka arz", "temettü", "bilanço"
]

# ==========================================
# 7. HABER ÇEKME
# ==========================================
def fetch_news_from_source(source, seen_links):
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
            items = soup.find_all("a", href=True)

        for item in items[:30]:
            title_elem = item.select_one(source["title_selector"]) if hasattr(item, 'select_one') else None
            if title_elem:
                title = title_elem.get_text(strip=True)
            else:
                title = item.get_text(strip=True)

            if item.name == "a":
                href = item.get("href", "")
            else:
                a_tag = item.find("a", href=True)
                href = a_tag.get("href", "") if a_tag else ""

            if not href or not title or len(title) < 20:
                continue

            if href.startswith("http"):
                full_url = href
            elif href.startswith("/"):
                full_url = source["link_prefix"] + href
            else:
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

    system = "Sen kıdemli bir finansal analistsin."
    user = f"""
Aşağıdaki son dakika haberlerini değerlendir.

KURALLAR:
1. Her haber için piyasa etkisini belirle: (+) olumlu, (-) olumsuz
2. Nötr/etkisiz haberleri ATLA
3. Her önemli haber için format:
   🟢 veya 🔴 *[KAYNAK(LAR)] BAŞLIK*
   📝 Özet: 1-2 cümle açıklama
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
                                        for p in pdf.pages[:5]
                                    )

                                print("=== HAM PDF (ilk 1000 karakter) ===")
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
