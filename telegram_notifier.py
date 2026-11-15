# -*- coding: utf-8 -*-
"""
Telegram Bildirim, Grafik Gönderim ve Saatlik/Günlük Kasa Raporu Modülü
"""

import json
import ssl
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from config import Config
from portfolio_simulator import PortfolioSimulator, now_tr
from strategy_engine import SignalSetup

TR_TZ = timezone(timedelta(hours=3))


def fmt_price(price: float) -> str:
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 100:
        return f"{price:,.3f}"
    if price >= 1:
        return f"{price:,.4f}"
    if price >= 0.01:
        return f"{price:,.5f}"
    if price >= 0.0001:
        return f"{price:,.6f}"
    return f"{price:,.8f}"


def fmt_usd_signed(val: float) -> str:
    return f"+{val:.2f}$" if val >= 0 else f"{val:.2f}$"


def fmt_pct_signed(val: float) -> str:
    return f"+%{val:.2f}" if val >= 0 else f"-%{abs(val):.2f}"


def format_altcoin_wt_signal(setup: SignalSetup, trade: Dict, current_bankroll: float) -> str:
    coin = setup.symbol.replace("USDT", "")
    is_long = setup.direction == "LONG"
    dir_badge = "🟢 LONG" if is_long else "🔴 SHORT"
    trend_line = "📈 Trend: UP" if setup.macro_trend_4h == "UP" else "📉 Trend: DOWN"
    div_label = "BULL DIVERGENCE (4H)" if (is_long and setup.is_divergence) else (
        "BEAR DIVERGENCE (4H)" if (not is_long and setup.is_divergence) else "(4H)"
    )
    vip_header = "🔥 <b>VIP ÇİFT ONAYLI SİNYAL (ALTCOIN BOT + WOXI)</b>\n" if setup.is_vip_double else ""

    margin = float(trade["margin_usd"])
    lev = int(trade["leverage"])
    notional = float(trade["notional_usd"])
    net_tp1_usd = notional * ((setup.tp1_pct - Config.ROUND_TRIP_FEE_PCT) / 100.0)
    net_sl_usd = notional * ((setup.sl_pct + Config.ROUND_TRIP_FEE_PCT) / 100.0)

    return (
        f"{vip_header}"
        f"#{coin}   {dir_badge}  <i>[4H Trend Uyumlu]</i>\n\n"
        f"📍 {div_label}\n"
        f"{trend_line} | WT: {setup.wt_value:.0f} | Güven: %{setup.confidence_pct}\n\n"
        f"💰 <b>Giriş (Entry):</b> <code>{fmt_price(setup.entry_price)}</code>\n"
        f"🚫 <b>Stop Loss:</b> <code>{fmt_price(setup.sl_price)}</code> (-%{setup.sl_pct:.1f})\n\n"
        f"🎯 <b>TP1 (%100 Komple Kapanış):</b> <code>{fmt_price(setup.tp1_price)}</code> (+%{setup.tp1_pct:.1f})\n"
        f"📌 <i>Referans TP2:</i> <code>{fmt_price(setup.tp2_price)}</code> (+%{setup.tp2_pct:.1f})\n\n"
        f"💼 <b>$100 Kasa Simülasyonu ({Config.MARGIN_PER_TRADE_PCT:.0f}% Marjin | {lev}x İzole):</b>\n"
        f"  • Marjin: <code>{margin:.2f}$</code> (Pozisyon: <code>{notional:.2f}$</code>)\n"
        f"  • TP1'de Net Kâr (%100 Kapat): <b><code>{fmt_usd_signed(net_tp1_usd)}</code></b> (+%{(setup.tp1_pct - Config.ROUND_TRIP_FEE_PCT)*lev:.1f})\n"
        f"  • SL Olursa Net Zarar: <code>-{net_sl_usd:.2f}$</code> (-%{(setup.sl_pct + Config.ROUND_TRIP_FEE_PCT)*lev:.1f})\n"
        f"  • Güncel Kasa: <code>{current_bankroll:.2f}$</code> | #{setup.uid}"
    )


def format_woxi_signal(setup: SignalSetup, trade: Dict, current_bankroll: float) -> str:
    is_long = setup.direction == "LONG"
    sig_title = "📈 LONG SIGNAL" if is_long else "📉 SHORT SIGNAL"
    vip_header = "🔥 <b>VIP ÇİFT ONAYLI SİNYAL (WOXI + ALTCOIN BOT)</b>\n" if setup.is_vip_double else ""

    margin = float(trade["margin_usd"])
    lev = int(trade["leverage"])
    notional = float(trade["notional_usd"])
    est_tp1_usd = notional * 0.40 * ((setup.tp1_pct - Config.ROUND_TRIP_FEE_PCT) / 100.0)
    est_sl_usd = min(margin, notional * ((setup.sl_pct + Config.ROUND_TRIP_FEE_PCT) / 100.0))
    now_str = now_tr().strftime("%d-%m-%Y %H:%M")

    return (
        f"{vip_header}"
        f"📩 #{setup.symbol}.P | {setup.timeframe} | <i>4H Trend: {setup.macro_trend_4h}</i>\n\n"
        f"<b>{sig_title}</b>\n"
        f"🎯 <b>Entry :</b> <code>{fmt_price(setup.entry_price)}</code>\n"
        f"🕐 <b>Time :</b> {now_str}\n\n"
        f"⏳ <b>Targets</b>\n"
        f"  • TP1 (%40 + BE): <code>{fmt_price(setup.tp1_price)}</code> (+%{setup.tp1_pct:.2f})\n"
        f"  • TP2 (%30)     : <code>{fmt_price(setup.tp2_price)}</code> (+%{setup.tp2_pct:.2f})\n"
        f"  • TP3 (%20)     : <code>{fmt_price(setup.tp3_price)}</code> (+%{setup.tp3_pct:.2f})\n"
        f"  • TP4 (%10 Run) : <code>{fmt_price(setup.tp4_price)}</code> (+%{setup.tp4_pct:.2f})\n\n"
        f"🧲 <b>Trend Line :</b> <code>{fmt_price(setup.trend_line)}</code>\n"
        f"❌ <b>Stop-Loss :</b> <code>{fmt_price(setup.sl_price)}</code> (-%{setup.sl_pct:.2f})\n\n"
        f"💼 <b>Kasa Simülasyonu ({Config.MARGIN_PER_TRADE_PCT:.0f}% Marjin | {lev}x İzole):</b>\n"
        f"  • Marjin: <code>{margin:.2f}$</code> | TP1 (%40) Tahmini: <code>{fmt_usd_signed(est_tp1_usd)}</code> | Maks SL: <code>-{est_sl_usd:.2f}$</code>\n"
        f"  • Güncel Kasa: <code>{current_bankroll:.2f}$</code> | #{setup.uid}"
    )


def format_trade_event_message(ev: Dict) -> str:
    etype = ev["event_type"]
    sym = ev["symbol"]
    coin = sym.replace("USDT", "")
    tf = ev["timeframe"]
    direction = ev["direction"]
    lev = int(ev.get("leverage", 10))
    pnl = float(ev["pnl_usd"])
    tot_pnl = float(ev["total_trade_pnl_usd"])
    bank = float(ev["bankroll_after"])
    init_b = float(ev.get("initial_bankroll", 100.0))
    growth_pct = (bank - init_b) / init_b * 100.0 if init_b > 0 else 0.0
    exit_p = float(ev["exit_price"])
    entry_p = float(ev["entry_price"])
    uid = ev["uid"]

    if etype == "ALT_TP1_FULL":
        return (
            f"✅ <b>#{coin} {direction} - TP1 VURULDU (%100 KOMPLE KAPANIŞ)!</b>\n\n"
            f"📍 Giriş: <code>{fmt_price(entry_p)}</code> ➡️ Çıkış: <code>{fmt_price(exit_p)}</code>\n"
            f"📈 Spot: <code>+%{ev['spot_pct']:.2f}</code> | {lev}x Net: <b><code>+%{ev['lev_pct']:.2f}</code></b>\n"
            f"💰 <b>Net Kâr:</b> <b><code>{fmt_usd_signed(pnl)}</code></b>\n"
            f"💼 <b>Güncel Kasa:</b> <b><code>{bank:.2f}$</code></b> ({fmt_pct_signed(growth_pct)})\n"
            f"⏰ {ev['time_str']} | #{uid}"
        )
    if etype == "ALT_SL":
        return (
            f"🛑 <b>#{coin} {direction} - STOP LOSS HIT!</b>\n\n"
            f"📍 Giriş: <code>{fmt_price(entry_p)}</code> ➡️ Stop: <code>{fmt_price(exit_p)}</code>\n"
            f"📉 Spot: <code>-%{abs(ev['spot_pct']):.2f}</code> | {lev}x Net: <code>-%{abs(ev['lev_pct']):.2f}</code>\n"
            f"💔 <b>Net Zarar:</b> <code>{fmt_usd_signed(pnl)}</code>\n"
            f"💼 <b>Güncel Kasa:</b> <b><code>{bank:.2f}$</code></b> ({fmt_pct_signed(growth_pct)})\n"
            f"⏰ {ev['time_str']} | #{uid}"
        )

    if etype in ("WOXI_TP1", "WOXI_TP2", "WOXI_TP3", "WOXI_TP4"):
        tp_label = etype.replace("WOXI_", "")
        icon = "🚀" if tp_label == "TP4" else "✅"
        closed_pct = int(ev["close_fraction_pct"])
        extra = " | İşlem Tamamen Kapandı" if tp_label == "TP4" else ""
        return (
            f"📩 #{sym}.P | {tf} ({direction})\n"
            f"{icon} <b>{tp_label} HIT</b> | 📊 Kapanan: %{closed_pct}{extra}\n"
            f"🎯 Çıkış: <code>{fmt_price(exit_p)}</code>\n"
            f"💰 <b>Kâr:</b> <b><code>{fmt_usd_signed(pnl)}</code></b> (+%{ev['lev_pct']:.2f} @ {lev}x)\n"
            f"💼 <b>İşlem Toplam:</b> <code>{fmt_usd_signed(tot_pnl)}</code> | <b>Kasa:</b> <b><code>{bank:.2f}$</code></b> ({fmt_pct_signed(growth_pct)})\n"
            f"#{uid}"
        )

    if etype in ("WOXI_BE_UPDATE", "WOXI_TRAIL_UPDATE"):
        reason = ev.get("extra_note") or ("Break-Even (TP1)" if etype == "WOXI_BE_UPDATE" else "Trailing Stop")
        return (
            f"📩 #{sym}.P | {tf}\n"
            f"🔄 <b>STOP UPDATED</b>\n"
            f"📌 Sebep: {reason}\n"
            f"🎯 Yeni Stop Seviyesi: <code>{fmt_price(exit_p)}</code>\n"
            f"#{uid}"
        )

    if etype == "WOXI_PROTECTED_EXIT":
        return (
            f"📩 #{sym}.P | {tf} ({direction})\n"
            f"🛡 <b>PROTECTED EXIT (Kâr Korumalı Çıkış)</b>\n"
            f"🎯 Çıkış: <code>{fmt_price(exit_p)}</code>\n"
            f"💰 <b>Son Parça:</b> <code>{fmt_usd_signed(pnl)}</code> | <b>İşlem Toplam Net:</b> <b><code>{fmt_usd_signed(tot_pnl)}</code></b>\n"
            f"💼 <b>Güncel Kasa:</b> <b><code>{bank:.2f}$</code></b> ({fmt_pct_signed(growth_pct)})\n"
            f"#{uid}"
        )

    if etype == "WOXI_SL":
        return (
            f"📩 #{sym}.P | {tf} ({direction})\n"
            f"🛑 <b>STOP-LOSS HIT</b>\n"
            f"🎯 Çıkış: <code>{fmt_price(exit_p)}</code>\n"
            f"💔 <b>Net Zarar:</b> <code>{fmt_usd_signed(pnl)}</code> (-%{abs(ev['lev_pct']):.2f} @ {lev}x)\n"
            f"💼 <b>Güncel Kasa:</b> <b><code>{bank:.2f}$</code></b> ({fmt_pct_signed(growth_pct)})\n"
            f"#{uid}"
        )

    if etype == "DEMO_TP_CLOSE":
        return (
            f"✅ <b>#{coin} {direction} - BYBIT DEMO TP / KÂRLI KAPANIŞ</b>\n"
            f"🎯 Çıkış: <code>{fmt_price(exit_p)}</code> | 💰 <b>Net:</b> <b><code>{fmt_usd_signed(pnl)}</code></b>\n"
            f"💼 <b>Güncel Kasa:</b> <b><code>{bank:.2f}$</code></b> ({fmt_pct_signed(growth_pct)}) | #{uid}"
        )

    if etype == "DEMO_SL_CLOSE":
        return (
            f"🛑 <b>#{coin} {direction} - BYBIT DEMO STOP KAPANIŞ</b>\n"
            f"🎯 Çıkış: <code>{fmt_price(exit_p)}</code> | 💔 <b>Net:</b> <b><code>{fmt_usd_signed(pnl)}</code></b>\n"
            f"💼 <b>Güncel Kasa:</b> <b><code>{bank:.2f}$</code></b> ({fmt_pct_signed(growth_pct)}) | #{uid}"
        )

    return ""


def format_periodic_report(
    report_type: str,
    sim: PortfolioSimulator,
    live_prices: Dict[str, float],
    snapshot: Optional[Dict] = None,
) -> str:
    """
    Saatlik (HOURLY), Günlük (DAILY) veya Manuel (/rapor) Kasa & TP/SL Bilançosu üretir.
    """
    now = now_tr()
    if snapshot:
        target_hour = snapshot.get("prev_hour", now.strftime("%Y-%m-%d %H:00"))
        target_day = snapshot.get("prev_day", now.strftime("%Y-%m-%d"))
        hour_start = float(snapshot.get("hour_start_bankroll", sim.bankroll))
        day_start = float(snapshot.get("day_start_bankroll", sim.bankroll))
        cash_bank = float(snapshot.get("current_bankroll", sim.bankroll))
    else:
        target_hour = now.strftime("%Y-%m-%d %H:00")
        target_day = now.strftime("%Y-%m-%d")
        hour_start = float(sim.state.get("hour_start_bankroll", sim.bankroll))
        day_start = float(sim.state.get("day_start_bankroll", sim.bankroll))
        cash_bank = sim.bankroll

    hour_events = sim.get_period_events(hour_str=target_hour)
    day_events = sim.get_period_events(date_str=target_day)

    def _stats(ev_list: List[Dict]):
        tp_cnt = sum(1 for e in ev_list if e["event_type"] in ("ALT_TP1_FULL", "WOXI_TP1", "WOXI_TP2", "WOXI_TP3", "WOXI_TP4", "DEMO_TP_CLOSE"))
        sl_cnt = sum(1 for e in ev_list if e["event_type"] in ("ALT_SL", "WOXI_SL", "DEMO_SL_CLOSE"))
        prot_cnt = sum(1 for e in ev_list if e["event_type"] == "WOXI_PROTECTED_EXIT")
        pnl_sum = sum(float(e.get("pnl_usd", 0.0)) for e in ev_list)
        return tp_cnt, sl_cnt, prot_cnt, pnl_sum

    h_tp, h_sl, h_prot, h_pnl = _stats(hour_events)
    d_tp, d_sl, d_prot, d_pnl = _stats(day_events)

    h_pct = (h_pnl / hour_start * 100.0) if hour_start > 0 else 0.0
    d_pct = (d_pnl / day_start * 100.0) if day_start > 0 else 0.0

    d_tot = d_tp + d_sl
    d_wr = (d_tp / d_tot * 100.0) if d_tot > 0 else 0.0

    init_b = float(sim.state.get("initial_bankroll", Config.DEFAULT_BANKROLL_USD))
    if sim.state.get("demo_synced") and sim.state.get("demo_unrealised_pnl") is not None:
        unrealized = round(float(sim.state["demo_unrealised_pnl"]), 2)
        equity = round(float(sim.state.get("demo_total_equity") or (cash_bank + unrealized)), 2)
        mode_tag = "BYBIT DEMO ALT HESAP"
    else:
        unrealized = sim.calc_unrealized_pnl(live_prices)
        equity = round(cash_bank + unrealized, 2)
        mode_tag = "SİMÜLASYON"
    tot_diff = cash_bank - init_b
    tot_pct = (tot_diff / init_b * 100.0) if init_b > 0 else 0.0

    # Son 1 saatteki işlem özeti satırları
    h_lines = []
    for ev in hour_events:
        if ev["event_type"] in ("WOXI_BE_UPDATE", "WOXI_TRAIL_UPDATE"):
            continue
        lbl = ev["event_type"].replace("ALT_TP1_FULL", "TP1 (%100)").replace("WOXI_", "").replace("DEMO_", "")
        h_lines.append(
            f"  • [{ev['time_str']}] #{ev['symbol']} ({ev['direction']}) ➡️ <b>{lbl}: {fmt_usd_signed(float(ev['pnl_usd']))}</b>"
        )
    h_detail = "\n".join(h_lines[-8:]) if h_lines else "  • <i>Bu saat diliminde kapanan TP/SL işlemi olmadı.</i>"

    if report_type == "DAILY":
        title = f"📅 <b>GÜN SONU KASA VE PERFORMANS RAPORU ({target_day})</b>"
    elif report_type == "HOURLY":
        title = f"🔔 <b>SAATLİK DURUM VE KASA RAPORU ({target_hour})</b>"
    else:
        title = f"📊 <b>ANLIK KASA VE PERFORMANS RAPORU ({now.strftime('%H:%M')})</b>"

    return (
        f"{title}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ <b>SAATLİK ÖZET ({target_hour}):</b>\n"
        f"  • ✅ TP: <b>{h_tp}</b> | 🛑 SL: <b>{h_sl}</b> | 🛡 Korumalı: <b>{h_prot}</b>\n"
        f"  • 💵 Saatlik Net: <b><code>{fmt_usd_signed(h_pnl)}</code> ({fmt_pct_signed(h_pct)})</b>\n"
        f"{h_detail}\n\n"
        f"📆 <b>GÜNLÜK PERFORMANS ({target_day}):</b>\n"
        f"  • ✅ TP: <b>{d_tp}</b> | 🛑 SL: <b>{d_sl}</b> | 🎯 Başarı Oranı: <b>%{d_wr:.1f}</b>\n"
        f"  • 🏦 Gün Başı Kasa: <code>{day_start:.2f}$</code>\n"
        f"  • 🚀 Günlük Net Kâr/Zarar: <b><code>{fmt_usd_signed(d_pnl)}</code> ({fmt_pct_signed(d_pct)})</b>\n\n"
        f"💼 <b>GENEL KASA DURUMU ({mode_tag} | {init_b:.2f}$ Başlangıç):</b>\n"
        f"  • 💵 Gerçekleşen Kasa: <b><code>{cash_bank:.2f}$</code></b> (Toplam: <b>{fmt_usd_signed(tot_diff)} / {fmt_pct_signed(tot_pct)}</b>)\n"
        f"  • 📈 Açık İşlemler ({len(sim.active_trades)} adet) Anlık PnL: <code>{fmt_usd_signed(unrealized)}</code>\n"
        f"  • ⚖️ Toplam Varlık (Equity): <b><code>{equity:.2f}$</code></b>"
    )


def format_open_trades_message(sim: PortfolioSimulator, live_prices: Dict[str, float]) -> str:
    if not sim.active_trades:
        return (
            f"📭 <b>Şu anda simülasyonda açık pozisyon bulunmuyor.</b>\n"
            f"💼 Güncel Kasa: <b><code>{sim.bankroll:.2f}$</code></b>"
        )
    lines = [f"📌 <b>AÇIK SİMÜLASYON POZİSYONLARI ({len(sim.active_trades)} adet)</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
    for uid, tr in sim.active_trades.items():
        sym = tr["symbol"]
        p = live_prices.get(sym, float(tr["entry_price"]))
        entry = float(tr["entry_price"])
        is_long = tr["direction"] == "LONG"
        spot_pct = ((p - entry) / entry * 100.0) if is_long else ((entry - p) / entry * 100.0)
        lev = int(tr["leverage"])
        rem = float(tr["remaining_fraction"])
        unr_usd = float(tr["notional_usd"]) * rem * (spot_pct / 100.0)
        d_icon = "🟢" if is_long else "🔴"
        if tr["engine"] == "ALTCOIN_WT_4H":
            eng = "WT-4H"
        elif tr["engine"] == "DEMO_RECOVERED":
            eng = "DEMO"
        else:
            eng = f"WOXI-{tr['timeframe']}"
        lines.append(
            f"{d_icon} <b>#{sym}</b> [{eng}] | Giriş: <code>{fmt_price(entry)}</code> | Anlık: <code>{fmt_price(p)}</code>\n"
            f"   Kalan: %{int(rem*100)} | Anlık: <b>{fmt_usd_signed(unr_usd)}</b> ({fmt_pct_signed(spot_pct*lev)} @ {lev}x) | SL: <code>{fmt_price(float(tr['current_sl']))}</code>"
        )
    lines.append(f"\n💼 Güncel Nakit Kasa: <b><code>{sim.bankroll:.2f}$</code></b>")
    return "\n".join(lines)


class TelegramNotifier:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        Config.reload()
        self.token = (token or Config.TELEGRAM_BOT_TOKEN).strip()
        self.chat_id = (chat_id or Config.TELEGRAM_CHAT_ID).strip()
        self._last_update_id: int = 0
        self._ssl_ctx = ssl.create_default_context()

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def get_bot_info(self) -> Optional[dict]:
        if not self.token:
            return None
        url = f"https://api.telegram.org/bot{self.token}/getMe"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=8, context=self._ssl_ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok"):
                    return data.get("result")
        except Exception:
            return None
        return None

    def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> Optional[int]:
        tgt_chat = chat_id or self.chat_id
        if not self.token or not tgt_chat or not text:
            return None
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload: Dict[str, object] = {
            "chat_id": tgt_chat,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = int(reply_to_message_id)
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=12, context=self._ssl_ctx) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                if res.get("ok"):
                    return res.get("result", {}).get("message_id")
        except Exception as exc:
            print(f"[UYARI] Telegram mesajı gönderilemedi: {exc}")
        return None

    def send_photo(
        self,
        photo_path: Path,
        caption: str,
        chat_id: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> Optional[int]:
        tgt_chat = chat_id or self.chat_id
        if not self.token or not tgt_chat or not photo_path.exists():
            return self.send_message(caption, chat_id=tgt_chat, reply_to_message_id=reply_to_message_id)

        url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        fields = {
            "chat_id": str(tgt_chat),
            "caption": caption,
            "parse_mode": "HTML",
        }
        if reply_to_message_id:
            fields["reply_to_message_id"] = str(reply_to_message_id)

        parts: List[bytes] = []
        for k, v in fields.items():
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{k}"\r\n\r\n'
                f"{v}\r\n".encode("utf-8")
            )

        img_bytes = photo_path.read_bytes()
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="photo"; filename="{photo_path.name}"\r\n'
                f"Content-Type: image/png\r\n\r\n"
            ).encode("utf-8")
            + img_bytes
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)

        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20, context=self._ssl_ctx) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                if res.get("ok"):
                    return res.get("result", {}).get("message_id")
        except Exception as exc:
            print(f"[UYARI] Telegram fotoğraf gönderilemedi, metin gönderiliyor: {exc}")
            return self.send_message(caption, chat_id=tgt_chat, reply_to_message_id=reply_to_message_id)
        return None

    def register_bot_commands(self) -> bool:
        if not self.token:
            return False
        url = f"https://api.telegram.org/bot{self.token}/setMyCommands"
        commands = [
            {"command": "demo", "description": "Bybit Alt Hesap Demo bakiyesi ve açık pozisyonlar"},
            {"command": "rapor", "description": "Saatlik, günlük TP/SL ve kasa raporu"},
            {"command": "acik", "description": "Takip edilen açık işlemler ve anlık PnL"},
            {"command": "tara", "description": "Hemen anlık Bybit taraması başlat"},
            {"command": "kasa", "description": "Demo kasayı ve bakiyeyi 100$ yap / sıfırla"},
            {"command": "oto_ac", "description": "Bybit Demo otomatik emirleri başlat"},
            {"command": "oto_kapat", "description": "Bybit Demo otomatik emirleri duraklat"},
            {"command": "durum", "description": "Tarayıcı durumu ve son tarama bilgisi"},
            {"command": "yardim", "description": "Strateji özeti ve komut listesi"},
        ]
        data = json.dumps({"commands": commands}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=8, context=self._ssl_ctx) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return bool(res.get("ok"))
        except Exception:
            return False

    def poll_commands(
        self,
        get_status_cb: Callable[[], str],
        trigger_scan_cb: Callable[[], str],
        get_report_cb: Optional[Callable[[], str]] = None,
        get_open_cb: Optional[Callable[[], str]] = None,
        set_bankroll_cb: Optional[Callable[[float], str]] = None,
        get_demo_cb: Optional[Callable[[], str]] = None,
        toggle_auto_cb: Optional[Callable[[bool], str]] = None,
    ) -> None:
        if not self.token:
            return
        url = f"https://api.telegram.org/bot{self.token}/getUpdates?offset={self._last_update_id + 1}&timeout=1"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=5, context=self._ssl_ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return

        if not data.get("ok"):
            return

        handled_cmds = set()
        for upd in data.get("result", []):
            upd_id = upd.get("update_id", 0)
            if upd_id > self._last_update_id:
                self._last_update_id = upd_id

            msg = upd.get("message") or upd.get("edited_message") or {}
            chat = msg.get("chat") or {}
            text = str(msg.get("text") or "").strip()
            sender_id = str(chat.get("id") or "").strip()

            if not sender_id or not text:
                continue

            if not self.chat_id:
                self.chat_id = sender_id
                from config import save_env_value
                save_env_value("TELEGRAM_CHAT_ID", sender_id)
                print(f"[TELEGRAM] Chat ID kaydedildi: {sender_id}")

            if sender_id != self.chat_id:
                continue

            parts = text.split()
            cmd = parts[0].lower().split("@")[0]
            if cmd in handled_cmds:
                continue
            handled_cmds.add(cmd)

            if cmd in ("/start", "/yardim", "/help"):
                welcome = (
                    "🤖 <b>WOXI-BM + Altcoin WaveTrend 4H (Bybit Standart Alt Demo Botu)</b>\n\n"
                    "📌 <b>Aktif Kurallar:</b>\n"
                    "  • <b>Bybit Demo Alt Hesap:</b> API bağlıysa sinyallerde otomatik emir açar (bağlı değilse $100 simülasyon)\n"
                    "  • <b>Sabit Giriş:</b> Her işleme kasanın <b>%10'u</b> | <b>10x İzole</b>\n"
                    "  • <b>Motor 1 (Altcoin WT 4H):</b> Yalnızca 4H Trend yönünde sinyal + Grafikli + <b>TP1'de (+%1.0) %100 Komple Kapanış</b>\n"
                    "  • <b>Motor 2 (WOXI CALMILO 1H/30m):</b> 4H Trend filtresi + 4 Kademeli TP + <b>Break-Even &amp; Trailing Stop</b>\n"
                    "  • <b>Raporlama:</b> Her saat başı ve gün sonunda otomatik TP/SL &amp; kasa bilançosu\n\n"
                    "⌨️ <b>Komutlar:</b>\n"
                    "  • /demo — Bybit Demo Alt Hesap cüzdanı ve açık pozisyonlar\n"
                    "  • /rapor — Saatlik ve günlük TP/SL, % getiri ve kasa bilançosu\n"
                    "  • /acik — Takip edilen açık işlemler\n"
                    "  • /tara — Anlık Bybit taraması başlat\n"
                    "  • /kasa 100 — Gerçek Bybit Demo USDT bakiyesini 100$ yap ve sıfırla\n"
                    "  • /oto_ac / /oto_kapat — Demo otomatik emirleri aç / duraklat\n"
                    "  • /durum — Tarayıcı durumu"
                )
                self.send_message(welcome, sender_id)
            elif cmd == "/demo":
                if get_demo_cb:
                    self.send_message(get_demo_cb(), sender_id)
            elif cmd in ("/oto_ac", "/otoac"):
                if toggle_auto_cb:
                    self.send_message(toggle_auto_cb(True), sender_id)
            elif cmd in ("/oto_kapat", "/otokapat"):
                if toggle_auto_cb:
                    self.send_message(toggle_auto_cb(False), sender_id)
            elif cmd in ("/rapor", "/gunluk", "/bakiye"):
                if get_report_cb:
                    self.send_message(get_report_cb(), sender_id)
            elif cmd in ("/acik", "/pozisyon"):
                if get_open_cb:
                    self.send_message(get_open_cb(), sender_id)
            elif cmd in ("/kasa", "/sifirla", "/reset"):
                if set_bankroll_cb:
                    val = 100.0
                    if len(parts) > 1:
                        try:
                            val = float(parts[1].replace(",", ".").replace("$", ""))
                        except Exception:
                            val = 100.0
                    self.send_message(set_bankroll_cb(val), sender_id)
            elif cmd == "/durum":
                self.send_message(get_status_cb(), sender_id)
            elif cmd == "/tara":
                self.send_message("🔎 Bybit USDT Vadeli pariteler (4H, 1H, 30m) taranıyor...", sender_id)
                self.send_message(trigger_scan_cb(), sender_id)
