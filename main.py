import ccxt
import pandas as pd
import pandas_ta as ta
import requests
import os
import sys

# --- CONFIG ---
TOKEN_TELEGRAM = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# --- SETTINGAN GAP DINAMIS ---
GAP_STRICT = 0.5  # Gap untuk Top Volume (Aman)
GAP_LOOSE  = 0.9  # Gap untuk Top Ticks (Agresif)

if not TOKEN_TELEGRAM or not CHAT_ID:
    print("Error: Token/Chat ID belum di-set!")
    sys.exit()

# === KRAKEN (USD ONLY) ===
exchange = ccxt.kraken({
    'enableRateLimit': True,
})

def kirim_notif(pesan):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage?chat_id={CHAT_ID}&text={pesan}&parse_mode=Markdown"
    try:
        requests.get(url)
    except Exception as e:
        print(f"Gagal kirim Telegram: {e}")

# 1. AMBIL TOP VOLUME (Hanya USD)
def get_top_volume_pairs():
    print("Sedang mengambil data Top Volume (Kraken USD)...")
    try:
        tickers = exchange.fetch_tickers()
        pairs = []
        for symbol, data in tickers.items():
            if symbol.endswith('/USD'):
                if 'EUR/' in symbol or 'GBP/' in symbol or 'AUD/' in symbol or 'CAD/' in symbol or 'JPY/' in symbol: continue
                if symbol.startswith('USDT') or symbol.startswith('USDC') or symbol.startswith('DAI') or symbol.startswith('PYUSD'): continue

                vol = data['quoteVolume'] if data['quoteVolume'] else 0
                pairs.append({'symbol': symbol, 'val': vol})
        
        hasil = pd.DataFrame(pairs).sort_values(by='val', ascending=False).head(50)['symbol'].tolist()
        print(f"✅ Sukses ambil {len(hasil)} koin Top Volume (USD).")
        return hasil
    except Exception as e:
        print(f"❌ ERROR AMBIL VOLUME: {e}") 
        return []

# 2. AMBIL TOP TICKS (Hanya USD)
def get_top_ticks_pairs():
    print("Sedang mengambil data Top Ticks (Kraken USD)...")
    try:
        tickers = exchange.fetch_tickers()
        pairs = []
        for symbol, data in tickers.items():
             if symbol.endswith('/USD'):
                if 'EUR/' in symbol or 'GBP/' in symbol or 'AUD/' in symbol or 'CAD/' in symbol or 'JPY/' in symbol: continue
                if symbol.startswith('USDT') or symbol.startswith('USDC') or symbol.startswith('DAI') or symbol.startswith('PYUSD'): continue

                vol = data['quoteVolume'] if data['quoteVolume'] else 0
                pairs.append({'symbol': symbol, 'val': vol})
        
        hasil = pd.DataFrame(pairs).sort_values(by='val', ascending=False).head(20)['symbol'].tolist()
        print(f"✅ Sukses ambil {len(hasil)} koin Top Activity (USD).")
        return hasil
    except Exception as e:
        print(f"❌ ERROR AMBIL TICKS: {e}")
        return []

# --- ANALISA UTAMA (DENGAN LOG DETIL) ---
def analyze_market(symbol, max_gap, source_label):
    clean_symbol = symbol.replace('/USD', '')
    try:
        # Cek Big Trend (ADX 2H)
        bars_2h = exchange.fetch_ohlcv(symbol, timeframe='2h', limit=50)
        df_2h = pd.DataFrame(bars_2h, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        adx_val = ta.adx(df_2h['h'], df_2h['l'], df_2h['c'], length=14)['ADX_14'].iloc[-2]
        
        if adx_val < 25: 
            print(f"Running {clean_symbol}... ❌ Skip (ADX Lemah: {adx_val:.1f})")
            return None

        # Cek Eksekusi (15m)
        bars_15m = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df_15m = pd.DataFrame(bars_15m, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        
        df_15m['ema13'] = ta.ema(df_15m['c'], length=13)
        df_15m['ema21'] = ta.ema(df_15m['c'], length=21)
        df_15m['ema100'] = ta.ema(df_15m['c'], length=100)
        stoch = ta.stoch(df_15m['h'], df_15m['l'], df_15m['c'], k=5, d=3, smooth_k=3)
        df_15m['stoch_k'] = stoch['STOCHk_5_3_3']
        
        # === DATA POINT ===
        idx = -2
        price = df_15m['c'].iloc[idx]
        e13, e21, e100 = df_15m['ema13'].iloc[idx], df_15m['ema21'].iloc[idx], df_15m['ema100'].iloc[idx]
        stoch_k = df_15m['stoch_k'].iloc[idx]
        
        # History
        e13_prev = df_15m['ema13'].iloc[idx-1]
        e21_prev = df_15m['ema21'].iloc[idx-1]
        stoch_k_prev = df_15m['stoch_k'].iloc[idx-1]
        e13_prev_2 = df_15m['ema13'].iloc[idx-2]
        
        # Hitung Gap
        gap = abs(e13 - e21) / e21 * 100
        
        # Status Stoch
        stoch_status = "NETRAL"
        is_cheap = (stoch_k < 40) or (stoch_k_prev < 40)
        is_expensive = (stoch_k > 60) or (stoch_k_prev > 60)
        
        if is_cheap: stoch_status = "MURAH"
        elif is_expensive: stoch_status = "MAHAL"

        # Logic
        bullish_cross = (e13 > e21) and (e13_prev <= e21_prev)
        bearish_cross = (e13 < e21) and (e13_prev >= e21_prev)
        bullish_curve = (e13 > e13_prev) and (e13_prev <= e13_prev_2) and (gap < max_gap)
        bearish_curve = (e13 < e13_prev) and (e13_prev >= e13_prev_2) and (gap < max_gap)

        icon = "💎" if source_label == "VOLUME" else "⚡"
        
        # === PRINT DATA LENGKAP UTK DEBUG ===
        # Kita format supaya rapi di log
        trend_short = "BULL" if e13 > e21 else "BEAR"
        log_msg = f"[{clean_symbol}] P:{price} | {trend_short} | E13:{e13:.2f} E21:{e21:.2f} | Gap:{gap:.2f}% | Stoch:{stoch_k:.0f}({stoch_status})"
        
        # Cek Kondisi
        if (price > e100 and e13 > e100 and e21 > e100 and is_cheap):
            if bullish_cross:
                print(f"✅ {log_msg} -> LONG CROSS")
                return f"{icon} *LONG ({source_label})*\nCoin: {clean_symbol}\nAction: ⚔️ CROSS (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
            elif bullish_curve:
                print(f"✅ {log_msg} -> LONG V-SHAPE")
                return f"{icon} *LONG ({source_label})*\nCoin: {clean_symbol}\nAction: 🧲 V-SHAPE (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
            else:
                # Masuk Area Buy, tapi belum ada trigger
                print(f"👀 {log_msg} -> Wait Trigger (Cross/Curve)")

        elif (price < e100 and e13 < e100 and e21 < e100 and is_expensive):
            if bearish_cross:
                print(f"✅ {log_msg} -> SHORT CROSS")
                return f"{icon} *SHORT ({source_label})*\nCoin: {clean_symbol}\nAction: 💀 CROSS (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
            elif bearish_curve:
                print(f"✅ {log_msg} -> SHORT A-SHAPE")
                return f"{icon} *SHORT ({source_label})*\nCoin: {clean_symbol}\nAction: 🧱 A-SHAPE (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
            else:
                # Masuk Area Sell, tapi belum ada trigger
                print(f"👀 {log_msg} -> Wait Trigger (Cross/Curve)")
        
        else:
            # Tidak memenuhi syarat Tren Utama atau Stoch
            alasan = "Trend Salah"
            if trend_short == "BULL" and not is_cheap: alasan = "Stoch Mahal"
            if trend_short == "BEAR" and not is_expensive: alasan = "Stoch Murah"
            print(f"❌ {log_msg} -> Skip ({alasan})")

        return None

    except Exception as e:
        print(f"Error analisa {clean_symbol}: {e}")
        return None

if __name__ == "__main__":
    print("🚀 Mulai Scanning (Kraken USD Only - Debug Mode)...")
    
    list_vol = get_top_volume_pairs()
    list_ticks = get_top_ticks_pairs()
    
    print("\n" + "="*60)
    print(f"💎 TOP 50 VOLUME (Gap Strict {GAP_STRICT}%):")
    print(", ".join([x.replace('/USD', '') for x in list_vol]))
    print("-" * 60)
    print(f"⚡ TOP 20 TICKS (Gap Loose {GAP_LOOSE}%):")
    print(", ".join([x.replace('/USD', '') for x in list_ticks]))
    print("="*60 + "\n")

    target_coins = {}
    for coin in list_ticks: target_coins[coin] = {'gap': GAP_LOOSE, 'label': 'TICKS'}
    for coin in list_vol: target_coins[coin] = {'gap': GAP_STRICT, 'label': 'VOLUME'}

    print(f"📊 Total Koin Unik (Gabungan): {len(target_coins)}")
    print("-" * 60)
    
    for coin, config in target_coins.items():
        hasil = analyze_market(coin, config['gap'], config['label'])
        if hasil:
            kirim_notif(hasil)
            
    print("-" * 60)
    print("🏁 Selesai.")
