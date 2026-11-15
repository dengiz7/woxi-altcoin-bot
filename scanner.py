# -*- coding: utf-8 -*-
"""
WOXI-BM (CALMILO) + Altcoin Bot (WaveTrend 4H) Canlı Tarayıcı,
$100 Kasa Yöneticisi ve Bybit Standart Alt Hesap Demo Al-Sat Motoru (Render 7/24 Uyumlu)
"""

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from bybit_client import BybitClient
from bybit_trader import BybitDemoTrader
from config import Config, save_env_value
from portfolio_simulator import PortfolioSimulator, now_tr
from strategy_engine import (
    SignalSetup,
    determine_4h_trend,
    evaluate_altcoin_wt_4h,
    evaluate_woxi_calmilo,
)
from telegram_notifier import (
    TelegramNotifier,
    format_altcoin_wt_signal,
    format_open_trades_message,
    format_periodic_report,
    format_trade_event_message,
    format_woxi_signal,
)


def reconcile_demo_state(
    sim: PortfolioSimulator,
    demo_trader: Optional[BybitDemoTrader],
    notifier: TelegramNotifier,
    dry_run: bool = False,
) -> None:
    """Bybit Demo hesabındaki gerçek bakiye ve pozisyonları yerel durumla eşitler."""
    if dry_run or demo_trader is None or not demo_trader.is_configured:
        return

    acc = demo_trader.get_demo_account_summary()
    if acc is not None:
        sim.sync_demo_account_summary(acc)

    if not demo_trader.enabled:
        return

    open_positions = demo_trader.get_open_positions()
    open_by_sym = {str(p.get("symbol") or ""): p for p in open_positions if p.get("symbol")}
    now_ms = int(time.time() * 1000)

    for uid, tr in list(sim.active_trades.items()):
        if not tr.get("demo_order_placed"):
            continue
        sym = str(tr.get("symbol") or "")
        if not sym or sym in open_by_sym:
            continue

        opened_ms = int(tr.get("demo_opened_at_ms") or 0)
        if opened_ms > 0 and (now_ms - opened_ms) < 5000:
            continue

        records = demo_trader.get_closed_pnl_records(
            symbol=sym,
            start_time_ms=(opened_ms - 5000) if opened_ms > 0 else None,
            limit=15,
        )
        matched = [
            r for r in records
            if int(r.get("updatedTime") or 0) >= (opened_ms - 5000)
        ] if opened_ms > 0 else records[:1]

        total_bybit_pnl = 0.0
        exit_price = float(tr.get("entry_price") or 0.0)
        if matched:
            for r in matched:
                try:
                    total_bybit_pnl += float(r.get("closedPnl") or 0.0)
                except Exception:
                    pass
            try:
                exit_price = float(matched[0].get("avgExitPrice") or exit_price)
            except Exception:
                pass

        already_counted = float(tr.get("realized_pnl_usd") or 0.0)
        pnl_delta = round(total_bybit_pnl - already_counted, 4) if matched else 0.0

        demo_trader.cancel_all_symbol_orders(sym)
        ev = sim.close_trade_externally(uid, exit_price=exit_price, pnl_usd=pnl_delta)
        if acc is not None:
            sim.sync_demo_account_summary(demo_trader.get_demo_account_summary())
        if ev and notifier.is_configured:
            msg_txt = format_trade_event_message(ev)
            if msg_txt:
                notifier.send_message(msg_txt, reply_to_message_id=ev.get("telegram_msg_id"))

    sim.reconcile_recovered_positions(open_positions)


def run_full_market_scan(
    client: BybitClient,
    sim: PortfolioSimulator,
    notifier: TelegramNotifier,
    demo_trader: Optional[BybitDemoTrader] = None,
    dry_run: bool = False,
) -> Tuple[int, Dict[str, Tuple[float, int]], str]:
    """
    Bybit'teki en yüksek hacimli 60 kripto USDT vadeli pariteyi 4H, 1H ve 30m mumlarda tarar.
    Döner: (yeni_sinyal_sayisi, trailing_lines_map, ozet_metni)
    """
    if not dry_run and demo_trader is not None and demo_trader.is_configured:
        acc = demo_trader.get_demo_account_summary()
        sim.sync_demo_account_summary(acc)

    tickers = client.get_top_usdt_perpetuals(Config.TOP_SYMBOLS_COUNT, Config.MIN_24H_TURNOVER_USD)
    if not tickers:
        return 0, {}, "⚠️ Bybit piyasa verisi alınamadı, bağlantı kontrol ediliyor."

    symbols = [t.symbol for t in tickers]
    for tr in sim.active_trades.values():
        if tr["symbol"] not in symbols:
            symbols.append(tr["symbol"])

    klines_4h = client.fetch_klines_batch(symbols, "240", Config.KLINE_LIMIT)
    klines_1h = client.fetch_klines_batch(symbols, "60", Config.KLINE_LIMIT)
    klines_30m = client.fetch_klines_batch(symbols, "30", Config.KLINE_LIMIT)

    trailing_lines: Dict[str, Tuple[float, int]] = {}
    candidate_setups: List[SignalSetup] = []
    macro_trends: Dict[str, str] = {}

    for sym in symbols:
        c4h = klines_4h.get(sym, [])
        trend_4h = determine_4h_trend(c4h)
        macro_trends[sym] = trend_4h

        # 1) Engine 1: Altcoin Bot (WaveTrend 4H) — Sadece 4H Trend UP/DOWN olduğunda
        if c4h and trend_4h in ("UP", "DOWN"):
            sig_alt = evaluate_altcoin_wt_4h(sym, c4h, trend_4h, generate_chart=True)
            if sig_alt and not sim.is_duplicate_signal(sig_alt):
                candidate_setups.append(sig_alt)

        # 2) Engine 2: WOXI-BM (CALMILO 1h & 30m) — Trailing line her zaman toplanır
        for _, tf_label, kmap in (("60", "1h", klines_1h), ("30", "30m", klines_30m)):
            candles_tf = kmap.get(sym, [])
            if not candles_tf:
                continue
            sig_woxi, curr_tl, curr_dir = evaluate_woxi_calmilo(sym, candles_tf, tf_label, trend_4h)
            if curr_tl > 0:
                trailing_lines[f"{sym}:{tf_label}"] = (curr_tl, curr_dir)
            if sig_woxi and not sim.is_duplicate_signal(sig_woxi):
                candidate_setups.append(sig_woxi)

    by_sym_dir: Dict[Tuple[str, str], List[SignalSetup]] = {}
    for s in candidate_setups:
        by_sym_dir.setdefault((s.symbol, s.direction), []).append(s)

    for s in candidate_setups:
        if len(by_sym_dir.get((s.symbol, s.direction), [])) > 1 or sim.has_opposite_or_same_open(s.symbol, s.direction):
            s.is_vip_double = True

    opened_count = 0
    max_open = max(1, Config.MAX_CONCURRENT_DEMO_TRADES)
    for setup in candidate_setups:
        if len(sim.active_trades) >= max_open:
            print(f"[BİLGİ] Maksimum {max_open} açık işlem sınırına ulaşıldı, {setup.symbol} atlandı.")
            continue

        trade = sim.open_trade(setup)
        opened_count += 1

        demo_note = ""
        if not dry_run and demo_trader is not None and demo_trader.is_configured and demo_trader.enabled:
            placed, demo_meta, demo_note = demo_trader.place_signal_order(setup, trade, sim.bankroll)
            if placed and demo_meta:
                sim.attach_demo_meta(setup.uid, demo_meta)

        if setup.engine == "ALTCOIN_WT_4H":
            msg_text = format_altcoin_wt_signal(setup, trade, sim.bankroll)
            print(f"[SİNYAL - ALTCOIN WT 4H] {setup.symbol} {setup.direction} @ {setup.entry_price}")
        else:
            msg_text = format_woxi_signal(setup, trade, sim.bankroll)
            print(f"[SİNYAL - WOXI CALMILO {setup.timeframe}] {setup.symbol} {setup.direction} @ {setup.entry_price}")

        if demo_note:
            msg_text += f"\n\n{demo_note}"

        if not dry_run and notifier.is_configured:
            if setup.engine == "ALTCOIN_WT_4H" and setup.chart_path and Path(setup.chart_path).exists():
                msg_id = notifier.send_photo(Path(setup.chart_path), msg_text)
            else:
                msg_id = notifier.send_message(msg_text)
            sim.set_telegram_msg_id(setup.uid, msg_id)

    up_cnt = sum(1 for v in macro_trends.values() if v == "UP")
    down_cnt = sum(1 for v in macro_trends.values() if v == "DOWN")
    sim.state["last_scan_time"] = now_tr().strftime("%Y-%m-%d %H:%M:%S")
    sim.save()

    summary = (
        f"✅ <b>Tarama Tamamlandı ({now_tr().strftime('%H:%M:%S')})</b>\n"
        f"• Taranan Parite: <b>{len(symbols)} adet</b> (4H Trend: 🟢 {up_cnt} UP / 🔴 {down_cnt} DOWN)\n"
        f"• Yeni Açılan İşlem: <b>{opened_count} adet</b>\n"
        f"• Şu An Açık İşlemler: <b>{len(sim.active_trades)} adet</b>\n"
        f"• Güncel Kasa: <b><code>{sim.bankroll:.2f}$</code></b>"
    )
    return opened_count, trailing_lines, summary


def process_price_and_events(
    client: BybitClient,
    sim: PortfolioSimulator,
    notifier: TelegramNotifier,
    trailing_lines: Dict[str, Tuple[float, int]],
    demo_trader: Optional[BybitDemoTrader] = None,
    dry_run: bool = False,
) -> Dict[str, float]:
    live_prices = client.get_all_last_prices()
    if not live_prices:
        return {}

    events = sim.update_active_trades(live_prices, trailing_lines=trailing_lines)
    for ev in events:
        text = format_trade_event_message(ev)
        if not text:
            continue
        demo_note = ""
        if not dry_run and demo_trader is not None:
            demo_note = demo_trader.handle_trade_event(ev)
        if demo_note:
            text += f"\n\n{demo_note}"
        print(f"[OLAY] {ev['symbol']} {ev['event_type']} -> {ev['pnl_usd']:+.2f}$ | Kasa: {ev['bankroll_after']:.2f}$")
        if not dry_run and notifier.is_configured:
            notifier.send_message(text, reply_to_message_id=ev.get("telegram_msg_id"))

    reconcile_demo_state(sim, demo_trader, notifier, dry_run=dry_run)
    return live_prices


def start_health_http_server(
    scan_lock: threading.Lock,
    client: BybitClient,
    sim: PortfolioSimulator,
    notifier: TelegramNotifier,
    demo_trader: BybitDemoTrader,
    trailing_holder: Dict[str, Dict[str, Tuple[float, int]]],
    dry_run: bool,
    port: int,
) -> None:
    """Render Web Service ve cron-job.org için 7/24 sağlık ve uyandırma sunucusu."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/scan"):
                with scan_lock:
                    opened, trailing, summary = run_full_market_scan(
                        client, sim, notifier, demo_trader=demo_trader, dry_run=dry_run
                    )
                    if trailing:
                        trailing_holder["data"] = trailing
                    body = json.dumps(
                        {
                            "ok": True,
                            "opened": opened,
                            "open_trades": len(sim.active_trades),
                            "bankroll_usd": sim.bankroll,
                            "summary": summary,
                        },
                        ensure_ascii=False,
                    ).encode("utf-8")
            else:
                with scan_lock:
                    body = json.dumps(
                        {
                            "ok": True,
                            "service": "woxi-altcoin-demo-bot",
                            "last_scan": sim.state.get("last_scan_time", ""),
                            "open_trades": len(sim.active_trades),
                            "bankroll_usd": sim.bankroll,
                            "demo_configured": demo_trader.is_configured,
                            "demo_auto_trade": demo_trader.enabled,
                        },
                        ensure_ascii=False,
                    ).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = HTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[SUNUCU] 7/24 Bulut Sağlık Sunucusu aktif -> Port {port} (/health, /scan)")


def main() -> None:
    parser = argparse.ArgumentParser(description="WOXI-BM + Altcoin WaveTrend 4H Sinyal & Bybit Demo Botu")
    parser.add_argument("--once", action="store_true", help="Tek seferlik tarama yap ve çık")
    parser.add_argument("--dry-run", action="store_true", help="Telegram ve Demo emri göndermeden test et")
    args = parser.parse_args()

    Config.reload()
    client = BybitClient()
    sim = PortfolioSimulator()
    demo_trader = BybitDemoTrader()
    notifier = TelegramNotifier()
    notifier._last_update_id = int(sim.state.get("last_update_id", 0))
    scan_lock = threading.Lock()

    if not args.dry_run and demo_trader.is_configured:
        reconcile_demo_state(sim, demo_trader, notifier, dry_run=args.dry_run)

    def _mode_label() -> str:
        if not demo_trader.is_configured:
            return "SİMÜLASYON MODU (API yok)"
        return "BAĞLI & OTOMATİK AÇIK" if demo_trader.enabled else "BAĞLI (DURAKLATILDI)"

    print("=" * 72)
    print("  WOXI-BM (CALMILO) + ALTCOIN BOT (WAVETREND 4H) BYBIT DEMO BOTU")
    print("=" * 72)
    print(f"  Başlangıç Kasası : {sim.state.get('initial_bankroll', 100.0):.2f}$")
    print(f"  Güncel Kasa      : {sim.bankroll:.2f}$ (Açık İşlem: {len(sim.active_trades)})")
    print(f"  Kasa Kuralı      : Sabit %{Config.MARGIN_PER_TRADE_PCT:.0f} Marjin | {Config.DEFAULT_LEVERAGE}x İzole")
    print(f"  Bybit Alt Demo   : {_mode_label()}")
    print(f"  Altcoin Bot      : 4H Trend Yönü Filtreli | TP1'de (+%{Config.ALT_TP1_PCT}) %100 Kapanış")
    print(f"  WOXI-BM Motoru   : 1H & 30m CALMILO | 4H Trend Filtreli | Break-Even & Trailing Stop")
    print(f"  Telegram Durumu  : {'BAĞLI' if notifier.is_configured else 'BEKLEMEDE (.env eksik)'}")
    print("=" * 72)

    if args.once:
        opened, trailing, summary = run_full_market_scan(
            client, sim, notifier, demo_trader=demo_trader, dry_run=args.dry_run
        )
        live_prices = process_price_and_events(
            client, sim, notifier, trailing, demo_trader=demo_trader, dry_run=args.dry_run
        )
        print(summary)
        print("-" * 72)
        print(format_periodic_report("MANUAL", sim, live_prices))
        return

    trailing_holder: Dict[str, Dict[str, Tuple[float, int]]] = {"data": {}}
    start_health_http_server(
        scan_lock=scan_lock,
        client=client,
        sim=sim,
        notifier=notifier,
        demo_trader=demo_trader,
        trailing_holder=trailing_holder,
        dry_run=args.dry_run,
        port=Config.PORT,
    )

    if notifier.is_configured:
        notifier.register_bot_commands()
        notifier.send_message(
            f"🚀 <b>WOXI + Altcoin WaveTrend 4H Botu Başlatıldı!</b>\n"
            f"🏦 <b>Mod:</b> <code>{_mode_label()}</code>\n"
            f"💼 <b>Güncel Kasa:</b> <b><code>{sim.bankroll:.2f}$</code></b> | <b>Açık İşlem:</b> <b>{len(sim.active_trades)}</b>\n"
            f"⏱ Saat başı ve gün sonunda otomatik TP/SL bilançosu gönderilecektir.\n"
            f"📌 Durum kontrolü için /demo, /rapor veya /kasa 100 yazabilirsiniz."
        )

    last_full_scan = 0.0

    def _get_status() -> str:
        with scan_lock:
            return (
                f"🟢 <b>Bot Aktif (7/24 Tarama &amp; Bybit Demo)</b>\n"
                f"• Mod: <code>{_mode_label()}</code>\n"
                f"• Son Tarama: <code>{sim.state.get('last_scan_time') or 'Henüz yapılmadı'}</code>\n"
                f"• Açık İşlemler: <b>{len(sim.active_trades)} adet</b>\n"
                f"• Güncel Kasa: <b><code>{sim.bankroll:.2f}$</code></b>"
            )

    def _trigger_scan() -> str:
        with scan_lock:
            _, trailing, summary = run_full_market_scan(
                client, sim, notifier, demo_trader=demo_trader, dry_run=args.dry_run
            )
            trailing_holder["data"] = trailing
            return summary

    def _get_report() -> str:
        with scan_lock:
            if not args.dry_run and demo_trader.is_configured:
                reconcile_demo_state(sim, demo_trader, notifier, dry_run=args.dry_run)
            prices = client.get_all_last_prices()
            return format_periodic_report("MANUAL", sim, prices)

    def _get_open() -> str:
        with scan_lock:
            if not args.dry_run and demo_trader.is_configured:
                reconcile_demo_state(sim, demo_trader, notifier, dry_run=args.dry_run)
            prices = client.get_all_last_prices()
            return format_open_trades_message(sim, prices)

    def _get_demo() -> str:
        with scan_lock:
            return demo_trader.format_demo_status_text(sim.bankroll)

    def _set_bankroll(val: float) -> str:
        with scan_lock:
            val_clamped = max(10.0, round(float(val), 2))
            closed_pos = 0
            cancelled_ords = 0
            real_wb = val_clamped
            note = ""
            if not args.dry_run and demo_trader.is_configured:
                closed_pos, cancelled_ords, real_wb, note = demo_trader.reset_demo_account(val_clamped)
            sim.reset_bankroll(real_wb)
            if not args.dry_run and demo_trader.is_configured:
                sim.sync_demo_account_summary(demo_trader.get_demo_account_summary())
            extra = f"\n⚠️ <i>{note}</i>" if note else ""
            demo_part = (
                f"\n• 🧹 Kapatılan Pozisyon: <code>{closed_pos}</code> | İptal Emir: <code>{cancelled_ords}</code>"
                if demo_trader.is_configured
                else ""
            )
            return (
                f"🔄 <b>KASA VE BYBIT DEMO BAKİYESİ SIFIRLANDI!</b>\n"
                f"💼 Yeni Başlangıç Kasası: <b><code>{sim.bankroll:.2f}$</code></b>\n"
                f"📌 Sabit Giriş: %{Config.MARGIN_PER_TRADE_PCT:.0f} ({sim.bankroll * Config.MARGIN_PER_TRADE_PCT / 100:.2f}$) | {Config.DEFAULT_LEVERAGE}x İzole"
                f"{demo_part}{extra}"
            )

    def _toggle_auto(enable: bool) -> str:
        demo_trader.enabled = enable
        save_env_value("DEMO_AUTO_TRADE_ENABLED", "true" if enable else "false")
        if enable:
            return "🟢 <b>Bybit Demo Alt Hesap Otomatik İşlem AKTİF!</b> Yeni sinyallerde otomatik demo emri açılacak."
        return "⏸ <b>Bybit Demo Otomatik İşlem DURAKLATILDI!</b> Sinyaller yalnızca Telegram ve simülasyona düşer."

    try:
        while True:
            try:
                prev_upd = notifier._last_update_id
                notifier.poll_commands(
                    get_status_cb=_get_status,
                    trigger_scan_cb=_trigger_scan,
                    get_report_cb=_get_report,
                    get_open_cb=_get_open,
                    set_bankroll_cb=_set_bankroll,
                    get_demo_cb=_get_demo,
                    toggle_auto_cb=_toggle_auto,
                )
                if notifier._last_update_id != prev_upd:
                    sim.state["last_update_id"] = notifier._last_update_id
                    sim.save()

                now_ts = time.time()
                with scan_lock:
                    if now_ts - last_full_scan >= Config.FULL_SCAN_COOLDOWN_SECONDS:
                        _, trailing, _ = run_full_market_scan(
                            client, sim, notifier, demo_trader=demo_trader, dry_run=args.dry_run
                        )
                        trailing_holder["data"] = trailing
                        last_full_scan = time.time()

                    live_prices = process_price_and_events(
                        client,
                        sim,
                        notifier,
                        trailing_holder["data"],
                        demo_trader=demo_trader,
                        dry_run=args.dry_run,
                    )

                    hour_changed, day_changed, snapshot = sim.check_time_rollovers()
                    if day_changed and Config.ENABLE_DAILY_REPORT and not args.dry_run and notifier.is_configured:
                        notifier.send_message(format_periodic_report("DAILY", sim, live_prices, snapshot=snapshot))
                    elif hour_changed and Config.ENABLE_HOURLY_REPORT and not args.dry_run and notifier.is_configured:
                        notifier.send_message(format_periodic_report("HOURLY", sim, live_prices, snapshot=snapshot))

                time.sleep(Config.SCAN_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"[HATA] Tarama döngüsü hatası (5 sn sonra devam edecek): {exc}")
                time.sleep(5)
    except KeyboardInterrupt:
        print("\n[BİLGİ] Bot kullanıcı tarafından durduruldu. Durum kaydedildi.")
        sim.save()


if __name__ == "__main__":
    main()
