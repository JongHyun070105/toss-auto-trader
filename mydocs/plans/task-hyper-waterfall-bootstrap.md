# Task Plan · hyper-waterfall-bootstrap

- Task slug: hyper-waterfall-bootstrap
- Date: 2026-05-13
- Owner: Hermes
- Related files:
  - AGENTS.md
  - mydocs/README.md
  - mydocs/manual/hyper_waterfall.md
  - mydocs/_templates/task_plan.md
  - mydocs/_templates/stage_report.md
  - mydocs/_templates/final_report.md
  - mydocs/orders/20260513.md
- Goal:
  - Batter's Eye 저장소에 Hyper-Waterfall Lite 산출물 구조를 추가한다.
  - AGENTS.md에 승인 게이트와 문서 경로를 명시한다.
  - npm install 금지 / npm ci 강제 규칙을 문서화한다.
- Non-goals:
  - GitHub Issue 자동화 전체 구축
  - 외부 PR 템플릿 체계 도입
  - Node 기반 CLI 도구 추가
- Risks:
  - 저장소 규모에 비해 프로세스가 과도해질 수 있음
  - 문서만 늘고 실제 사용되지 않을 수 있음
- Acceptance criteria:
  1. `mydocs/` 아래 orders/plans/reports/manual/templates 구조가 생긴다.
  2. AGENTS.md에서 Hyper-Waterfall Lite와 npm ci 정책을 확인할 수 있다.
  3. repo 전체 검색 시 `npm install` 문구가 남아있지 않다.
- Planned stages:
  1. 레퍼런스 방법론 검토 및 저장소 맞춤 축약
  2. mydocs 구조/템플릿 추가
  3. AGENTS.md 정책 반영 및 npm 정책 명문화
  4. 검색 검증 및 보고
- Verification plan:
  - `search_files`로 `npm install` 잔존 여부 확인
  - `read_file`로 AGENTS.md와 mydocs 산출물 확인
- Approval needed before implementation?: no (user explicitly requested repo 적용)
