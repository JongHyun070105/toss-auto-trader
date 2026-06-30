#!/usr/bin/env python3
"""
yfinance를 사용하여 코스닥 전 종목의 15년치(2011-2026) 일봉 데이터를 수집하고
로컬 SQLite 데이터베이스에 캐싱하는 스크립트.
"""
import argparse
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tqdm import tqdm
import yfinance as yf
import pandas as pd

def load_symbols(path: str) -> list[str]:
    symbols = []
    if not Path(path).exists():
        raise FileNotFoundError(f"Symbols file not found: {path}")
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        sym = line.split(',')[0].strip()
        if sym:
            symbols.append(sym)
    return symbols

def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # candle_cache 테이블 생성
    cur.execute("""
        CREATE TABLE IF NOT EXISTS candle_cache (
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            open_price TEXT NOT NULL,
            high_price TEXT NOT NULL,
            low_price TEXT NOT NULL,
            close_price TEXT NOT NULL,
            volume TEXT NOT NULL,
            currency TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY(symbol, interval, timestamp)
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_candle_cache_symbol_interval_time ON candle_cache(symbol, interval, timestamp);")
    conn.commit()
    conn.close()

def main():
    ap = argparse.ArgumentParser(description="Yahoo Finance KOSDAQ 15Y Candle Cacher")
    ap.add_argument("--symbols-file", default="research/kosdaq_symbols.txt")
    ap.add_argument("--db-path", default="data/edge_research_universe_15y.sqlite3")
    ap.add_argument("--start", default="2011-01-01")
    ap.add_argument("--end", default=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"))
    ap.add_argument("--chunk-size", type=int, default=50, help="Number of symbols to fetch in a single yfinance request")
    args = ap.parse_args()

    symbols = load_symbols(args.symbols_file)
    print(f"로드 완료: {len(symbols)}종목")
    init_db(args.db_path)

    # 50개씩 청크 분할 수집
    chunks = [symbols[i:i + args.chunk_size] for i in range(0, len(symbols), args.chunk_size)]
    
    conn = sqlite3.connect(args.db_path)
    cur = conn.cursor()
    
    ok_count = 0
    total_inserted = 0
    fetched_at = datetime.now(timezone.utc).isoformat()

    print(f"15년치 일봉 데이터 수집 시작 ({args.start} ~ {args.end})...")
    
    # tqdm으로 수집 진행률 표시
    for chunk in tqdm(chunks, desc="Downloading KOSDAQ candles"):
        ticker_map = {f"{sym}.KQ": sym for sym in chunk}
        tickers = list(ticker_map.keys())
        
        try:
            # yfinance로 한 번에 다운로드
            df = yf.download(
                tickers, 
                start=args.start, 
                end=args.end, 
                group_by="ticker", 
                threads=True, 
                progress=False
            )
        except Exception as e:
            print(f"\n[오류] 청크 다운로드 실패 (첫종목: {chunk[0]}): {e}")
            time.sleep(5)
            continue

        # 다운로드된 데이터를 SQLite에 저장
        for ticker, symbol in ticker_map.items():
            try:
                # 단일 종목 다운로드 결과 슬라이싱
                if len(tickers) == 1:
                    sub_df = df
                else:
                    if ticker not in df.columns.levels[0]:
                        continue
                    sub_df = df[ticker]
                
                # 데이터 유효성 검사
                sub_df = sub_df.dropna(subset=['Open', 'High', 'Low', 'Close'])
                if sub_df.empty:
                    continue
                
                records = []
                for date, row in sub_df.iterrows():
                    # toss timestamp 포맷 모방 (YYYY-MM-DDT00:00:00+09:00)
                    ts = date.strftime("%Y-%m-%dT00:00:00+09:00")
                    
                    records.append((
                        symbol,
                        "1d",
                        ts,
                        str(int(row['Open'])) if not pd.isna(row['Open']) else "0",
                        str(int(row['High'])) if not pd.isna(row['High']) else "0",
                        str(int(row['Low'])) if not pd.isna(row['Low']) else "0",
                        str(int(row['Close'])) if not pd.isna(row['Close']) else "0",
                        str(int(row['Volume'])) if not pd.isna(row['Volume']) else "0",
                        "KRW",
                        "{}",
                        fetched_at
                    ))
                
                if records:
                    cur.executemany("""
                        INSERT OR REPLACE INTO candle_cache 
                        (symbol, interval, timestamp, open_price, high_price, low_price, close_price, volume, currency, raw_json, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, records)
                    total_inserted += len(records)
                    ok_count += 1
                    
            except Exception as e:
                # 개별 종목 파싱 에러 방지
                continue
        
        # 청크마다 중간 커밋
        conn.commit()
        time.sleep(0.5)

    conn.close()
    print(f"\n수집 완료! 성공: {ok_count}/{len(symbols)}종목, 총 {total_inserted:,}행 적재 완료.")
    return 0

if __name__ == "__main__":
    main()
