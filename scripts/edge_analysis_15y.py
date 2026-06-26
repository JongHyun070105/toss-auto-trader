#!/usr/bin/env python3
"""
15년치 대량 일봉 데이터를 기반으로 한 코스닥 갭 하락 패턴 정밀 백테스트 스크립트.
- 시장 벤치마크(Market Baseline)를 분리하여 순수 알파(Alpha) 검증
- 매크로 국면(Regime)별 성과 분해
- 슬리피지 민감도 테스트 및 마이크로 필터 조합 검증
"""
import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict
from statistics import mean, median, stdev

DB_PATH = "data/edge_research_universe_15y.sqlite3"
MIN_HISTORY = 100
ROUND_TRIP_COST = 0.0035

def load_data():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # 최소 히스토리 필터
    cur.execute("SELECT symbol FROM candle_cache GROUP BY symbol HAVING count(*) >= ?", (MIN_HISTORY,))
    valid_symbols = {r[0] for r in cur.fetchall()}
    
    cur.execute("SELECT symbol, timestamp, open_price, close_price, volume FROM candle_cache ORDER BY symbol, timestamp")
    
    data = defaultdict(list)
    for row in cur.fetchall():
        symbol = row[0]
        if symbol in valid_symbols:
            data[symbol].append({
                'date': row[1][:10],
                'open': float(row[2]),
                'close': float(row[3]),
                'volume': int(row[4])
            })
    conn.close()
    return data

def build_market_baseline(data):
    """일별 모든 종목의 시가 대비 종가 수익률 평균(동일가중)을 구해 벤치마크로 설정"""
    daily_returns = defaultdict(list)
    for symbol, candles in data.items():
        for c in candles:
            if c['open'] <= 0:
                continue
            ret = (c['close'] - c['open']) / c['open']
            daily_returns[c['date']].append(ret)
            
    market_baseline = {}
    for d, rets in daily_returns.items():
        market_baseline[d] = mean(rets) if rets else 0.0
    return market_baseline

def get_regime(date_str):
    """날짜별 시장 Regime 구분"""
    year = int(date_str[:4])
    # 코로나 락다운 및 유동성 랠리 (2020.02 ~ 2021.12)
    if (date_str >= '2020-02-01') and (date_str <= '2021-12-31'):
        return 'COVID_Bubble'
    # 금리인상 하락장 (2022.01 ~ 2022.12)
    elif year == 2022:
        return 'Inflation_Bear'
    # 장기 박스권 횡보장 (2011 ~ 2016)
    elif year in [2011, 2012, 2013, 2014, 2015, 2016]:
        return 'Sideways_Box'
    # 일반 안정 성장/횡보 국면 (2017 ~ 2019, 2023 ~ 2024)
    elif year in [2017, 2018, 2019, 2023, 2024]:
        return 'Normal_Regime'
    # 최근 2025~2026 국면
    elif year in [2025, 2026]:
        return 'Recent_Regime'
    return 'Other'

def run_backtest(data, market_baseline):
    results = []
    
    for symbol, candles in data.items():
        for i in range(20, len(candles)):
            prev_close = candles[i-1]['close']
            if prev_close <= 0:
                continue
            
            gap = (candles[i]['open'] - prev_close) / prev_close
            
            # 갭 하락 3% 이상 조건 진입
            if gap <= -0.03:
                buy_price = candles[i]['open']
                sell_price = candles[i]['close']
                if buy_price <= 0:
                    continue
                
                # 수수료 차감 전 순수 수익률
                raw_return = (sell_price - buy_price) / buy_price
                
                # 동일 거래일 시장 전체의 시가 대비 종가 평균 수익률
                m_ret = market_baseline.get(candles[i]['date'], 0.0)
                
                # 시장 수익률을 차감한 초과수익률(Alpha)
                alpha_return = raw_return - m_ret
                
                # 20일 평균 거래량 대비 당일 거래량 배수
                avg_vol = mean(c['volume'] for c in candles[i-20:i])
                vol_ratio = candles[i]['volume'] / avg_vol if avg_vol > 0 else 1.0
                
                results.append({
                    'date': candles[i]['date'],
                    'symbol': symbol,
                    'price': buy_price,
                    'raw_return': raw_return,
                    'alpha_return': alpha_return,
                    'vol_ratio': vol_ratio,
                    'regime': get_regime(candles[i]['date']),
                    'year': candles[i]['date'][:4]
                })
                
    return pd.DataFrame(results)

def print_metrics(df, title, slippage=0.0):
    if df.empty:
        print(f"\n{title}: 신호 없음")
        return
        
    net_returns = df['raw_return'] - ROUND_TRIP_COST - slippage
    wins = net_returns > 0
    
    avg_net = net_returns.mean()
    med_net = net_returns.median()
    win_rate = wins.mean()
    avg_alpha = df['alpha_return'].mean() # 시장 대비 초과수익률
    
    print(f"  신호 수: {len(df):,}건 | 수수료+슬립 후 평균: {avg_net*100:+.3f}% (중앙 {med_net*100:+.3f}%) | 승률: {win_rate*100:.1f}% | 시장초과(Alpha): {avg_alpha*100:+.3f}%")

def main():
    print("15년치 대량 데이터 로드 중...")
    data = load_data()
    total_candles = sum(len(v) for v in data.values())
    print(f"로드 완료: {len(data)}종목, 총 {total_candles:,}행")
    
    if total_candles == 0:
        print("데이터베이스에 일봉 데이터가 없습니다. 수집을 먼저 실행해야 합니다.")
        return 1
        
    market_baseline = build_market_baseline(data)
    print("시장 벤치마크(Market Baseline) 구축 완료.")
    
    print("\n" + "=" * 60)
    print(" 갭 하락 3% 반등 패턴 15년 정밀 백테스트 (시가 매수 → 당일 종가 매도)")
    print("=" * 60)
    
    df = run_backtest(data, market_baseline)
    
    print(f"\n[1] 전체 통합 결과 (왕복 수수료 0.35% 차감 후)")
    print_metrics(df, "전체")
    
    # 1. Regime별 분해
    print("\n[2] 시장 국면(Regime)별 분석 (Alpha 초과수익률 검증)")
    for regime in ['Sideways_Box', 'Normal_Regime', 'COVID_Bubble', 'Inflation_Bear', 'Recent_Regime']:
        sub = df[df['regime'] == regime]
        regime_names = {
            'Sideways_Box': '횡보 박스피 장세 (2011~2016)',
            'Normal_Regime': '평시 일반 장세 (2017~19, 23~24)',
            'COVID_Bubble': '코로나 유동성 버블기 (2020~2021)',
            'Inflation_Bear': '금리인상 폭락 하락장 (2022)',
            'Recent_Regime': '최근 최근 장세 (2025~2026)'
        }
        print(f"  * {regime_names[regime]}:")
        print_metrics(sub, regime)

    # 2. 연도별 분석
    print("\n[3] 연도별 상세 성과")
    for y in sorted(df['year'].unique()):
        sub = df[df['year'] == y]
        print_metrics(sub, f"  {y}년")

    # 3. 소액투자 필터 조합 검사 (5000원 이상 + 거래량 조용함)
    print("\n[4] 정밀 마이크로 필터링 조합 비교")
    filters = [
        ("전체 (필터 없음)", lambda d: d),
        ("5000원 미만 잡주", lambda d: d[d['price'] < 5000]),
        ("5000원 이상 주식", lambda d: d[d['price'] >= 5000]),
        ("5000원 이상 + 거래량 잠잠함 (vol_ratio < 1.0)", lambda d: d[(d['price'] >= 5000) & (d['vol_ratio'] < 1.0)]),
        ("5000원 이상 + 거래량 폭발함 (vol_ratio >= 1.0)", lambda d: d[(d['price'] >= 5000) & (d['vol_ratio'] >= 1.0)])
    ]
    for label, filter_fn in filters:
        sub = filter_fn(df)
        print(f"  * {label}:")
        print_metrics(sub, label)

    # 4. 슬리피지 민감도 테스트
    print("\n[5] 슬리피지 민감도 테스트 (5000원 이상 + 거래량 잠잠한 핵심 전략 기준)")
    core_df = df[(df['price'] >= 5000) & (df['vol_ratio'] < 1.0)]
    for slip in [0.0, 0.001, 0.002, 0.003]:
        print(f"  * 추가 슬리피지 {slip*100:.1f}% 적용 시 (총 비용 {(ROUND_TRIP_COST+slip)*100:.2f}%)")
        print_metrics(core_df, "슬리피지 테스트", slippage=slip)

    print("\n" + "=" * 60)
    print("분석 완료")
    return 0

if __name__ == "__main__":
    main()
