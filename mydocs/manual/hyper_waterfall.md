# Hyper-Waterfall Lite for Batter's Eye

## 왜 적용하나
Batter's Eye는 단순 CRUD 앱이 아니라 다음이 동시에 얽힌다.
- 브랜드/UI 일관성
- 온보딩/인증/레벨 테스트 플로우
- AI 개인화
- 훈련 루프와 결과 해석
- 향후 3D/Unity pitch renderer 검토

이런 작업은 한 번 잘못 꺾이면 구현량이 많아질수록 되돌리기 어렵다.  
그래서 이 저장소는 완전한 heavy process 대신 **Hyper-Waterfall Lite**를 사용한다.

## 핵심 원칙
1. 사람은 방향과 승인 게이트를 가진다.
2. AI는 문서 초안, 구현, 검증, 보고를 빠르게 수행한다.
3. 긴 채팅보다 저장소 문서를 우선한다.
4. 큰 작업은 `orders → plans → reports` 산출물을 남긴다.
5. 소스 수정 전, 적어도 한 번은 계획 문서로 범위를 고정한다.

## 적용 대상
다음 작업은 Lite 절차를 따른다.
- 새 화면 흐름 추가
- 온보딩/인증/결제/AI 연동 같은 상태 전이 변경
- 디자인 시스템 구조 변경
- 패키지/빌드 체인/스크립트 수정
- 외부 렌더러(Unity 등) 도입 검토

다음 작업은 간소화 가능하다.
- 오탈자 수정
- 단일 카피 수정
- 스타일 수치 미세 조정
- 테스트 한두 줄 수정

## 작업 순서
1. `orders/YYYYMMDD.md`에 오늘 작업 등록
2. `plans/task-<slug>.md` 작성
3. 승인 또는 범위 확정
4. 구현 / 테스트 / 캡처 검증
5. 필요하면 `reports/stage-*.md` 작성
6. 작업 종료 시 `reports/final-*.md` 작성

## 승인 게이트
다음 상황에서는 바로 구현하지 말고 먼저 계획을 보여준다.
- 파일 3개 이상을 건드릴 때
- 사용자 플로우가 달라질 때
- 외부 API/모델/패키지 선택이 포함될 때
- UI 방향이 한 번에 크게 바뀔 때

## 이 저장소 전용 규칙
- 디자인 단일 기준은 `DESIGN.md`
- 에이전트 작업 기준은 `AGENTS.md`
- AI 개인화 기본 모델 타깃은 Gemini 2.5 Flash Lite
- API 키가 없으면 fallback planner를 유지
- pitch scene 현실감은 Flutter 개선 → 필요 시 Unity 분리 검토 순서
- OMX 0.17+에서는 DESIGN.md 기반 `$design` 워크플로와 Hermes MCP bridge를 활용할 수 있지만, 저장소 문서가 항상 최종 기준이다.

## 영감으로 반영한 오픈소스 패턴
- `andrej-karpathy-skills` → 짧고 강한 운영 문서를 선호
- `MemPalace`, `hermes-agent` → 메모리/작업 기억을 문서와 상태로 외부화
- `awesome-claude-code`, `SuperClaude Framework`, `mattpocock/skills` → 반복 작업은 스킬/가이드로 추상화
- `autoresearch` → 나중에 훈련 데이터/리서치 자동화 확장 가능성

## Node / npm 보안 규칙
> 중요: 이 저장소에서는 `npm install`을 사용하지 않는다.

- 문서, 스크립트, 작업 예시, AI 응답 모두 `npm ci` 기준으로 작성한다.
- lockfile이 없는 저장소에서는 임의로 `npm install`로 대체하지 말고 사용자 승인 또는 별도 계획을 요청한다.
- `.sh` 예시를 작성할 때도 동일하다.
