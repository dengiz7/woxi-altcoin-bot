# -*- coding: utf-8 -*-
"""
WOXI-BM (CALMILO) + Altcoin Bot (WaveTrend 4H) Birleşik Sinyal ve $100 Kasa Simülatörü Konfigürasyonu
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
STATE_PATH = BASE_DIR / "state.json"
CHARTS_DIR = BASE_DIR / "charts"


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                values[key] = val
    except Exception as exc:
        print(f"[UYARI] {path.name} okunurken hata: {exc}")
    return values


def load_env_file(env_path: Path = ENV_PATH) -> None:
    """Yerel .env dosyasını yükler; Telegram bilgisi yoksa mevcut kardeş projeden devralır."""
    local_vals = _parse_env_file(env_path)
    for k, v in local_vals.items():
        if k not in os.environ or not os.environ[k]:
            os.environ[k] = v

    # Mevcut bybit-fib-scanner projesinde Telegram kuruluysa otomatik devral
    sibling_env = BASE_DIR.parent / "bybit-fib-scanner" / ".env"
    if sibling_env.exists():
        sib_vals = _parse_env_file(sibling_env)
        copied = False
        for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            if (key not in os.environ or not os.environ[key]) and sib_vals.get(key):
                os.environ[key] = sib_vals[key]
                copied = True
        if copied and not env_path.exists():
            # İlk kurulumda yerel .env dosyasına kopyala ki kullanıcı tek yerden yönetebilsin
            lines = [
                f"TELEGRAM_BOT_TOKEN={os.environ.get('TELEGRAM_BOT_TOKEN', '')}",
                f"TELEGRAM_CHAT_ID={os.environ.get('TELEGRAM_CHAT_ID', '')}",
            ]
            try:
                env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except Exception:
                pass


def save_env_value(key: str, value: str, env_path: Path = ENV_PATH) -> None:
    os.environ[key] = str(value)
    lines = []
    found = False
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _ = stripped.split("=", 1)
                if k.strip() == key:
                    lines.append(f"{key}={value}")
                    found = True
                    continue
            lines.append(raw_line)
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


load_env_file()


class Config:
    # --- Telegram Ayarları ---
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    # --- Borsa ve Tarama Ayarları (Bybit V5 Public USDT Perpetual - API Key Gerektirmez) ---
    TOP_SYMBOLS_COUNT: int = int(os.getenv("TOP_SYMBOLS_COUNT", "60"))
    MIN_24H_TURNOVER_USD: float = float(os.getenv("MIN_24H_TURNOVER_USD", "15000000"))
    KLINE_LIMIT: int = int(os.getenv("KLINE_LIMIT", "220"))
    SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "30"))
    FULL_SCAN_COOLDOWN_SECONDS: int = int(os.getenv("FULL_SCAN_COOLDOWN_SECONDS", "180"))

    # --- $100 Kasa Simülasyonu Ayarları (Gerçek Emir Açmaz) ---
    DEFAULT_BANKROLL_USD: float = float(os.getenv("DEFAULT_BANKROLL_USD", "100.0"))
    MARGIN_PER_TRADE_PCT: float = float(os.getenv("MARGIN_PER_TRADE_PCT", "10.0"))
    DEFAULT_LEVERAGE: int = int(os.getenv("DEFAULT_LEVERAGE", "10"))
    ROUND_TRIP_FEE_PCT: float = float(os.getenv("ROUND_TRIP_FEE_PCT", "0.08"))

    # --- Engine 1: Altcoin Bot (WaveTrend 4H - Trend Yönü + TP1 %100 Kapanış) ---
    WT_N1: int = int(os.getenv("WT_N1", "10"))
    WT_N2: int = int(os.getenv("WT_N2", "21"))
    WT_OB_LEVEL: float = float(os.getenv("WT_OB_LEVEL", "60.0"))
    WT_OS_LEVEL: float = float(os.getenv("WT_OS_LEVEL", "-60.0"))
    ALT_TP1_PCT: float = float(os.getenv("ALT_TP1_PCT", "1.0"))
    ALT_TP2_PCT: float = float(os.getenv("ALT_TP2_PCT", "3.0"))
    ALT_SL_PCT: float = float(os.getenv("ALT_SL_PCT", "4.0"))
    ALT_TP1_CLOSE_RATIO: float = float(os.getenv("ALT_TP1_CLOSE_RATIO", "1.0"))

    # --- Engine 2: WOXI-BM (CALMILO 1H & 30m - 4H Trend Filtreli + Trailing Stop) ---
    WOXI_ATR_PERIOD: int = int(os.getenv("WOXI_ATR_PERIOD", "14"))
    WOXI_ATR_MULT: float = float(os.getenv("WOXI_ATR_MULT", "3.0"))
    WOXI_MAX_SL_PCT: float = float(os.getenv("WOXI_MAX_SL_PCT", "6.0"))

    # --- Otomatik Rapor Saatleri (TSİ / UTC+3) ---
    ENABLE_HOURLY_REPORT: bool = os.getenv("ENABLE_HOURLY_REPORT", "true").lower() in ("1", "true", "yes", "on")
    ENABLE_DAILY_REPORT: bool = os.getenv("ENABLE_DAILY_REPORT", "true").lower() in ("1", "true", "yes", "on")

    # --- Bybit V5 Standart Alt Hesap Demo Trading Ayarları ---
    BYBIT_DEMO_API_KEY: str = os.getenv("BYBIT_DEMO_API_KEY", "").strip()
    BYBIT_DEMO_API_SECRET: str = os.getenv("BYBIT_DEMO_API_SECRET", "").strip()
    BYBIT_DEMO_BASE_URL: str = os.getenv("BYBIT_DEMO_BASE_URL", "https://api-demo.bybit.com").strip()
    DEMO_AUTO_TRADE_ENABLED: bool = os.getenv("DEMO_AUTO_TRADE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    MAX_CONCURRENT_DEMO_TRADES: int = int(os.getenv("MAX_CONCURRENT_DEMO_TRADES", "10"))

    # --- Bulut (Render / Docker) HTTP Sunucu Ayarı ---
    PORT: int = int(os.getenv("PORT", "8080"))

    @classmethod
    def reload(cls) -> None:
        load_env_file()
        cls.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        cls.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        cls.BYBIT_DEMO_API_KEY = os.getenv("BYBIT_DEMO_API_KEY", "").strip()
        cls.BYBIT_DEMO_API_SECRET = os.getenv("BYBIT_DEMO_API_SECRET", "").strip()
        cls.BYBIT_DEMO_BASE_URL = os.getenv("BYBIT_DEMO_BASE_URL", "https://api-demo.bybit.com").strip()
        cls.DEMO_AUTO_TRADE_ENABLED = os.getenv("DEMO_AUTO_TRADE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
        cls.MAX_CONCURRENT_DEMO_TRADES = int(os.getenv("MAX_CONCURRENT_DEMO_TRADES", "10"))
        cls.PORT = int(os.getenv("PORT", "8080"))
