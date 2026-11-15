# WOXI-BM (CALMILO) + Altcoin Bot (WaveTrend 4H) — Bybit Standart Alt Demo & 7/24 Bulut Botu

Bu bot, **Bybit V5 Standart Alt Hesap (Subaccount) Demo Trading** (`https://api-demo.bybit.com`) üzerine otomatik işlem açar (API anahtarı girilmemişse `$100.00` simülasyon modunda çalışır), Telegram'dan grafik + saatlik/günlük bilanço gönderir ve **Render Free (Frankfurt) + cron-job.org** ile bilgisayar kapalıyken 7/24 bulutta çalışır.

## Aktif Strateji Kuralları
1. **Engine 1 — Altcoin Bot (WaveTrend 4H):**
   - LazyBear WaveTrend (`10, 21, 4`) ve **4H Ana Trend yönü** (`LONG + Trend: UP` / `SHORT + Trend: DOWN`) filtresi kullanır.
   - Sinyallerde karanlık temalı `WaveTrend 4H` grafiği üretip gönderir.
   - **TP1 (+%1.0)** hedefinde pozisyonun **%100'ünü komple kapatır**. Stop-Loss: `-%4.0`.
2. **Engine 2 — WOXI-BM (CALMILO 1H & 30m):**
   - `1h` ve `30m` mumlarda `CALMILO:Trend Line` (ATR 14, 3.0x SuperTrend) kırılımını tarar; **4H Ana Trend filtresi** uygular.
   - 4 Kademeli TP (`%40`, `%30`, `%20`, `%10 Runner`) + TP1'de otomatik **Break-Even** + saatlik **Trailing Stop** güncellemesi yapar (maks. `STOP_LOSS` `%6.0`).
3. **Kasa Yönetimi:**
   - Sabit **%10 Kasa Marjin** + **10x İzole Kaldıraç** (`MAX_CONCURRENT_DEMO_TRADES=10`).

---

## 1. Bybit Standart Alt Hesap Demo API Anahtarı Alma (Ana Botla Çakışmaz!)

Mevcut Bybit Demo hesabında başka bir bot (`Fib15Bot`) çalıştığı için tamamen ayrı bir kasa açıyoruz:
1. Bybit web sitesinden **Ana Hesabına** giriş yap.
2. Profil menüsünden **Alt Hesaplar (Subaccounts)** -> **Alt Hesap Oluştur** -> **Standart Alt Hesap (Standard Subaccount)** seç (UTA aktif olsun; *Custodial* veya *AI Subaccount* seçme).
3. Oluşturduğun yeni alt hesaba **Hesap Değiştir (Switch)** diyerek geç.
4. Sağ üst/profil menüsünden **Demo Trading (Deneme İşlemleri)** moduna geçiş yap.
5. **Demo Trading** ekranının içindeyken **API Yönetimi -> Yeni Anahtar Oluştur** deyip **Read-Write** + **Contract Trade (Order, Position)** izinleriyle `API Key` ve `API Secret` al.
6. Botu çalıştırdıktan sonra Telegram sohbetinden `/kasa 100` yazdığında bot yeni alt hesabın varsayılan `50.000$` demo bakiyesini otomatik **`100.00$`**'a çeker!

---

## 2. Bilgisayar Kapalıyken 7/24 Ücretsiz Bulut Kurulumu (`Render Frankfurt + cron-job.org`)

### Adım A: GitHub'a Yükle
1. [github.com](https://github.com) üzerinde `woxi-altcoin-bot` adında yeni (istersen Private) bir repository oluştur.
2. **`GITHUB_YUKLE`** klasörü içindeki tüm dosyaları bu GitHub deposunun ana dizinine yükle (`.env` ve `state.json` kesinlikle yüklenmez).

### Adım B: Render (Frankfurt - Kredi Kartsız `0$`) Kurulumu
1. [render.com](https://render.com) üzerinde **New + -> Web Service** seçip `woxi-altcoin-bot` deponu bağla (`render.yaml` ayarları otomatik tanınır):
   - **Region:** `Frankfurt (EU Central)` *(Bybit API erişimi için mutlaka Frankfurt olmalı!)*
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python scanner.py`
   - **Health Check Path:** `/health`
   - **Instance Type:** `Free`
2. **Environment Variables** bölümüne şu 4 anahtarı ekle:
   - `TELEGRAM_BOT_TOKEN` = *(Bot Token'ın)*
   - `TELEGRAM_CHAT_ID` = *(Chat ID'n)*
   - `BYBIT_DEMO_API_KEY` = *(Yeni Alt Hesap Demo API Key)*
   - `BYBIT_DEMO_API_SECRET` = *(Yeni Alt Hesap Demo API Secret)*
3. **Deploy Web Service**'e tıkla (`https://woxi-altcoin-demo-bot-xxxx.onrender.com` gibi adres oluşur).

### Adım C: `cron-job.org` ile 7/24 Uyanık Tutma
1. [cron-job.org](https://cron-job.org) hesabında yeni job aç:
   - **URL:** `https://SENIN-RENDER-ADRESIN.onrender.com/health`
   - **Schedule:** Her **5 dakikada bir** (`*/5`)
2. Kaydet. Artık bilgisayarın kapalıyken sistem 7/24 bulutta tarama yapar ve yeni Alt Hesap Demo hesabında otomatik işlem açar.

---

## Telegram Komutları
- `/demo` — Bybit Standart Alt Hesap cüzdanı ve gerçek açık pozisyonlar
- `/rapor` — Saatlik & günlük TP/SL, % getiri ve kasa bilançosu
- `/acik` — Aktif takip edilen işlemler ve anlık PnL
- `/tara` — Anlık manuel tarama başlat
- `/kasa 100` — Demo USDT bakiyesini `100.00$` olarak sıfırla
- `/oto_ac` / `/oto_kapat` — Otomatik Demo emir göndermeyi aç / duraklat
- `/durum` — Tarayıcı ve sunucu durumu
