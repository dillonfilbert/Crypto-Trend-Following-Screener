import asyncio
import ccxt.async_support as ccxt  # PENTING: Pakai versi Async
import pandas as pd
import pandas_ta as ta
import requests
import os
import sys

# --- CONFIG ---
TOKEN_TELEGRAM = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# --- SETTINGAN GAP DINAMIS ---
GAP_STRICT = 0.5  # Gap untuk Top Volume
GAP_LOOSE  = 0.9  # Gap untuk Top Ticks

if not TOKEN_TELEGRAM or not CHAT_ID:
    print("Error: Token/Chat ID belum di-set!")
    sys.exit()

# === KRAKEN (USD ONLY - ASYNC) ===
# Kita pakai instance exchange yang sama untuk semua request
exchange = ccxt.kraken({
    'enableRateLimit': True,  # CCXT akan otomatis mengatur antrian biar gak kena ban
})

def kirim_notif(pesan):
    # Telegram tetap synchronous (request biasa) biar simpel, karena cuma kirim sesekali
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage?chat_id={CHAT_ID}&text={pesan}&parse_mode=Markdown"
    try:
        requests.get(url, timeout=10)
    except Exception as e:
        print(f"Gagal kirim Telegram: {e}")

# --- FUNGSI AMBIL LIST KOIN (Tetap Sequential di awal gak masalah) ---
async def get_market_pairs():
    print("Sedang mengambil data pasar (Volume & Ticks)...")
    try:
        tickers = await exchange.fetch_tickers()
        pairs_vol = []
        pairs_ticks = []
        
        for symbol, data in tickers.items():
            if symbol.endswith('/USD'):
                if 'EUR/' in symbol or 'GBP/' in symbol or 'AUD/' in symbol or 'CAD/' in symbol or 'JPY/' in symbol: continue
                if symbol.startswith('USDT') or symbol.startswith('USDC') or symbol.startswith('DAI') or symbol.startswith('PYUSD'): continue

                vol = data['quoteVolume'] if data['quoteVolume'] else 0
                
                # Masukkan ke list mentah
                pairs_vol.append({'symbol': symbol, 'val': vol})
                pairs_ticks.append({'symbol': symbol, 'val': vol}) # Di Kraken Vol ≈ Activity
        
        # Sortir
        top_vol = pd.DataFrame(pairs_vol).sort_values(by='val', ascending=False).head(50)['symbol'].tolist()
        top_ticks = pd.DataFrame(pairs_ticks).sort_values(by='val', ascending=False).head(20)['symbol'].tolist()
        
        return top_vol, top_ticks
    except Exception as e:
        print(f"❌ ERROR AMBIL DATA PASAR: {e}") 
        return [], []

# --- ANALISA CORE (ASYNC) ---
# Fungsi ini akan dijalankan berbarengan untuk banyak koin
async def analyze_coin(symbol, max_gap, source_label):
    clean_symbol = symbol.replace('/USD', '')
    try:
        # 1. AMBIL DATA TREND (1H) - Limit 100
        # Kita pakai 'await' supaya dia tidak memblokir koin lain saat nunggu data
        bars_trend = await exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
        df_trend = pd.DataFrame(bars_trend, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        adx_val = ta.adx(df_trend['h'], df_trend['l'], df_trend['c'], length=14)['ADX_14'].iloc[-2]
        
        if adx_val < 25: 
            return f"❌ {clean_symbol} -> Skip (ADX 1H Lemah: {adx_val:.1f})"

        # 2. AMBIL DATA EKSEKUSI (15m) - Limit 500 (Presisi)
        bars_15m = await exchange.fetch_ohlcv(symbol, timeframe='15m', limit=500)
        df_15m = pd.DataFrame(bars_15m, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        
        # Hitung Indikator (CPU Bound - Cepat)
        df_15m['ema13'] = ta.ema(df_15m['c'], length=13)
        df_15m['ema21'] = ta.ema(df_15m['c'], length=21)
        df_15m['ema100'] = ta.ema(df_15m['c'], length=100)
        stoch = ta.stoch(df_15m['h'], df_15m['l'], df_15m['c'], k=5, d=3, smooth_k=3)
        df_15m['stoch_k'] = stoch['STOCHk_5_3_3']
        
        # Data Point
        idx = -2
        price = df_15m['c'].iloc[idx]
        e13, e21, e100 = df_15m['ema13'].iloc[idx], df_15m['ema21'].iloc[idx], df_15m['ema100'].iloc[idx]
        stoch_k = df_15m['stoch_k'].iloc[idx]
        
        # History
        e13_prev = df_15m['ema13'].iloc[idx-1]
        e21_prev = df_15m['ema21'].iloc[idx-1]
        stoch_k_prev = df_15m['stoch_k'].iloc[idx-1]
        e13_prev_2 = df_15m['ema13'].iloc[idx-2]
        
        gap = abs(e13 - e21) / e21 * 100
        
        stoch_status = "NETRAL"
        is_cheap = (stoch_k < 40) or (stoch_k_prev < 40)
        is_expensive = (stoch_k > 60) or (stoch_k_prev > 60)
        
        if is_cheap: stoch_status = "MURAH"
        elif is_expensive: stoch_status = "MAHAL"

        bullish_cross = (e13 > e21) and (e13_prev <= e21_prev)
        bearish_cross = (e13 < e21) and (e13_prev >= e21_prev)
        bullish_curve = (e13 > e13_prev) and (e13_prev <= e13_prev_2) and (gap < max_gap)
        bearish_curve = (e13 < e13_prev) and (e13_prev >= e13_prev_2) and (gap < max_gap)

        icon = "💎" if source_label == "VOLUME" else "⚡"
        trend_short = "BULL" if e13 > e21 else "BEAR"
        log_msg = f"[{clean_symbol}] P:{price} | {trend_short} | E100:{e100:.2f} | Gap:{gap:.2f}% | Stoch:{stoch_k:.0f}({stoch_status})"
        
        result_msg = None
        log_output = ""

        # Logic Decision
        if (price > e100 and e13 > e100 and e21 > e100 and is_cheap):
            if bullish_cross:
                log_output = f"✅ {log_msg} -> LONG CROSS"
                result_msg = f"{icon} *LONG ({source_label})*\nCoin: {clean_symbol}\nAction: ⚔️ CROSS (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
            elif bullish_curve:
                log_output = f"✅ {log_msg} -> LONG V-SHAPE"
                result_msg = f"{icon} *LONG ({source_label})*\nCoin: {clean_symbol}\nAction: 🧲 V-SHAPE (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
            else:
                log_output = f"👀 {log_msg} -> Wait Trigger"

        elif (price < e100 and e13 < e100 and e21 < e100 and is_expensive):
            if bearish_cross:
                log_output = f"✅ {log_msg} -> SHORT CROSS"
                result_msg = f"{icon} *SHORT ({source_label})*\nCoin: {clean_symbol}\nAction: 💀 CROSS (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
            elif bearish_curve:
                log_output = f"✅ {log_msg} -> SHORT A-SHAPE"
                result_msg = f"{icon} *SHORT ({source_label})*\nCoin: {clean_symbol}\nAction: 🧱 A-SHAPE (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
            else:
                log_output = f"👀 {log_msg} -> Wait Trigger"
        
        else:
            alasan = "Trend Salah"
            if trend_short == "BULL":
                if not is_cheap: alasan = "Stoch Mahal"
                elif price <= e100: alasan = "Price < EMA100"
            if trend_short == "BEAR":
                if not is_expensive: alasan = "Stoch Murah"
                elif price >= e100: alasan = "Price > EMA100"
            
            log_output = f"❌ {log_msg} -> Skip ({alasan})"

        return {'log': log_output, 'notif': result_msg}

    except Exception as e:
        return f"Error analisa {clean_symbol}: {e}"

# --- MAIN LOOP ASYNC ---
async def main():
    print("🚀 Mulai Scanning (Kraken USD - ASYNC TURBO MODE)...")
    
    # 1. Ambil List Koin
    list_vol, list_ticks = await get_market_pairs()
    
    if not list_vol:
        print("Gagal ambil data pasar. Exit.")
        await exchange.close()
        return

    print("\n" + "="*60)
    print(f"💎 TOP 50 VOLUME: {', '.join([x.replace('/USD', '') for x in list_vol])}")
    print("-" * 60)
    print(f"⚡ TOP 20 TICKS: {', '.join([x.replace('/USD', '') for x in list_ticks])}")
    print("="*60 + "\n")

    # 2. Siapkan Daftar Tugas (Tasks)
    target_coins = {}
    for coin in list_ticks: target_coins[coin] = {'gap': GAP_LOOSE, 'label': 'TICKS'}
    for coin in list_vol: target_coins[coin] = {'gap': GAP_STRICT, 'label': 'VOLUME'} # Timpa jika duplikat
    
    print(f"📊 Total Koin Unik: {len(target_coins)} -> Memproses Serentak...")
    
    tasks = []
    for coin, config in target_coins.items():
        # Masukkan semua fungsi analisa ke dalam antrian tugas
        tasks.append(analyze_coin(coin, config['gap'], config['label']))
    
    # 3. JALANKAN SEMUA BERSAMAAN (GATHER)
    # Ini adalah magic-nya. Python akan menembak request sekaligus (dengan rate limit safe)
    results = await asyncio.gather(*tasks)
    
    # 4. Proses Hasil
    print("-" * 60)
    for res in results:
        if isinstance(res, dict):
            print(res['log']) # Print Log
            if res['notif']:
                kirim_notif(res['notif']) # Kirim Telegram
                print("   └── 📨 Notifikasi terkirim!")
        else:
            # Kalau error string
            print(res)
            
    print("-" * 60)
    print("🏁 Selesai.")
    
    # Jangan lupa tutup koneksi async
    await exchange.close()

if __name__ == "__main__":
    # Jalankan Event Loop
    asyncio.run(main())
