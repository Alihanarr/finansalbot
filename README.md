# Finansalbot

Finansal piyasaları günlük olarak takip eden, yapay zeka destekli otomatik analiz ve haber botu.

---

## Türkçe

### Proje Hakkında

Finansalbot, Türk finansal piyasalarını günlük olarak takip etmek amacıyla geliştirilmiş bir otomasyon sistemidir. Birden fazla kaynaktan veri toplayarak yapay zeka ile yorumlar ve sonuçları Telegram üzerinden iletir.

Proje; sabah bülteni analizi, gün ortası raporu ve sürekli haber akışı olmak üzere üç ana modülden oluşmaktadır. İleride geliştirilecek fiyat tahmin modelinin veri altyapısı olarak da tasarlanmıştır.

### Özellikler

- **Sabah Bülteni** — Tacirler Yatırım günlük bültenini PDF olarak çeker, yapay zeka ile analiz eder ve Telegram'a gönderir
- **Gün Ortası Raporu** — Garanti BBVA gün ortası notlarını işler, sabah raporuyla karşılaştırmalı analiz üretir
- **Son Dakika Haber Akışı** — Bloomberg HT, Doviz.com, Ekonomim.com ve Bigpara'dan finans haberlerini çeker; çakışan haberleri tespit eder ve önem sırasına göre özetler
- **Canlı Piyasa Verisi** — Yahoo Finance üzerinden BIST-100, BIST-30, USD/TL ve EUR/TL verilerini anlık olarak çeker
- **Yapay Zeka Yorumu** — Tüm analizler Grok-3-mini modeli ile üretilir
- **Telegram Entegrasyonu** — Tüm çıktılar formatlanmış şekilde Telegram'a iletilir

### Kullanılan Teknolojiler

| Kütüphane | Kullanım Amacı |
|---|---|
| `requests` | HTTP istekleri ve API çağrıları |
| `playwright` | JavaScript destekli sayfa scraping |
| `pdfplumber` | PDF metin çıkarımı |
| `beautifulsoup4` | HTML parsing |

**API'ler:** xAI Grok API, Telegram Bot API, Yahoo Finance API

### Otomasyon

GitHub Actions ve cron job ile belirli saatlerde otomatik olarak çalışır. Çalışma geçmişi `history.json` dosyasında saklanır; aynı raporun birden fazla gönderilmesi önlenir.

### Kurulum

```bash
git clone https://github.com/Alihanarr/finansalbot.git
cd finansalbot
pip install -r requirements.txt
playwright install chromium
```

Gerekli ortam değişkenleri:

```
GROK_API_KEY
TELEGRAM_TOKEN
TELEGRAM_CHAT_ID
```

### Sonraki Aşama

Bu proje, ilerleyen dönemde geliştirilecek fiyat tahmin modelinin veri altyapısını oluşturmaktadır. Toplanan piyasa verileri makine öğrenimi modelleri için girdi olarak kullanılacaktır.

---

## English

### About

Finansalbot is an automated system designed to track Turkish financial markets on a daily basis. It collects data from multiple sources, interprets it using AI, and delivers the results via Telegram.

The project consists of three main modules: morning bulletin analysis, midday report, and continuous news monitoring. It is also designed to serve as the data infrastructure for a price prediction model to be developed in a future phase.

### Features

- **Morning Bulletin** — Fetches the Tacirler Yatırım daily bulletin as a PDF, analyzes it with AI, and sends it to Telegram
- **Midday Report** — Processes Garanti BBVA midday notes and generates a comparative analysis against the morning report
- **Breaking News Feed** — Scrapes financial news from Bloomberg HT, Doviz.com, Ekonomim.com, and Bigpara; detects duplicate stories across sources and summarizes by importance
- **Live Market Data** — Fetches real-time BIST-100, BIST-30, USD/TRY and EUR/TRY data via Yahoo Finance
- **AI Commentary** — All analyses are generated using the Grok-3-mini model
- **Telegram Integration** — All outputs are formatted and delivered via Telegram

### Tech Stack

| Library | Purpose |
|---|---|
| `requests` | HTTP requests and API calls |
| `playwright` | JavaScript-rendered page scraping |
| `pdfplumber` | PDF text extraction |
| `beautifulsoup4` | HTML parsing |

**APIs:** xAI Grok API, Telegram Bot API, Yahoo Finance API

### Automation

Runs automatically at scheduled times via GitHub Actions and cron jobs. Execution history is stored in `history.json` to prevent duplicate reports from being sent.

### Setup

```bash
git clone https://github.com/Alihanarr/finansalbot.git
cd finansalbot
pip install -r requirements.txt
playwright install chromium
```

Required environment variables:

```
GROK_API_KEY
TELEGRAM_TOKEN
TELEGRAM_CHAT_ID
```

### Next Phase

This project serves as the data infrastructure for a price prediction model to be developed in the next phase. The collected market data will be used as input for machine learning models.
