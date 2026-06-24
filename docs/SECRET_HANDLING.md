# Secret handling

이 프로젝트는 API 키를 저장소에 저장하지 않는다.

## 권장 테스트 방식

대화/로그에 노출된 키는 재발급한다. 테스트가 필요하면 아래 스크립트를 사용한다.

```bash
cd toss-auto-trader-lab
chmod +x scripts/api_smoke_no_store.sh
./scripts/api_smoke_no_store.sh 005930
```

- 첫 입력: Toss API KEY 또는 client_id
- 두 번째 입력: Toss SECRET KEY 또는 client_secret
- 두 번째 입력은 터미널에 표시되지 않는다.
- 값은 파일에 저장하지 않고 해당 프로세스 환경변수로만 사용한다.
- 실행 후 `TOSS_DRY_RUN=true`, `TOSS_LIVE_TRADING=false`로 read-only 테스트만 수행한다.

## 절대 금지

- 키를 README, 코드, 테스트, 커밋에 저장
- 실주문 테스트를 API 연결 확인과 동시에 수행
- 키를 다른 사람/봇/공개 채널에 재사용
