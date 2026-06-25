#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import urllib.request
import urllib.parse


def fetch_kosdaq_symbols() -> list[str]:
    print("네이버 금융 모바일 API를 사용하여 KOSDAQ 종목 리스트를 가져오는 중...")
    symbols = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 2500개 정도로 pageSize를 넉넉하게 주어 한번에 모든 종목을 가져옵니다.
    url = "https://m.stock.naver.com/api/json/sise/siseListJson.nhn?menu=market_sum&sosok=1&pageSize=2500"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_data = resp.read().decode("utf-8")
            data = json.loads(raw_data)
            
            result = data.get("result", {})
            item_list = result.get("itemList", [])
            for item in item_list:
                cd = item.get("cd")
                # ETF나 ETN 등 제외 옵션이 필요하다면 체크 (여기서는 etf/etn flag 활용)
                is_etf = item.get("etf", False)
                is_etn = item.get("etn", False)
                if cd and not is_etf and not is_etn:
                    symbols.append(cd)
            print(f"전체 코스닥 종목 수 (ETF/ETN 제외): {len(symbols)}")
    except Exception as e:
        print(f"네이버 금융 API 호출 중 오류 발생: {e}")
        
    return symbols


def main() -> int:
    try:
        tickers = fetch_kosdaq_symbols()
        if not tickers:
            print("오류: 코스닥 종목 리스트를 가져오지 못했습니다.")
            return 1
            
        research_dir = Path("research")
        research_dir.mkdir(parents=True, exist_ok=True)
        
        output_file = research_dir / "kosdaq_symbols.txt"
        output_file.write_text("\n".join(tickers) + "\n")
        print(f"성공: {len(tickers)}개의 코스닥 종목 기호를 {output_file}에 저장했습니다.")
        return 0
    except Exception as e:
        print(f"오류가 발생했습니다: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
