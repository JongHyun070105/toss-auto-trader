# AI Workflow Inspirations for Batter's Eye

이 문서는 최근 참고할 만한 AI 오픈소스 저장소에서 **지금 이 저장소에 바로 흡수할 원칙만** 추린 메모다.

## 1. andrej-karpathy-skills
- 긴 설명보다 짧고 강한 운영 문서를 선호한다.
- 따라서 이 저장소는 `AGENTS.md`와 `DESIGN.md`를 짧은 단일 기준 문서로 유지한다.

## 2. MemPalace / hermes-agent
- 기억은 채팅 로그에만 의존하지 않는다.
- 사용자 플로우, AI 추천 결과, 작업 계획, 검증 근거는 가능한 한 저장소 문서와 앱 상태로 외부화한다.

## 3. awesome-claude-code / SuperClaude / mattpocock/skills
- 반복되는 판단은 스킬/체크리스트/워크플로로 추상화한다.
- 이 저장소에서는 `mydocs/manual/`, `AGENTS.md`, `DESIGN.md`가 그 역할을 맡는다.

## 4. autoresearch
- 나중에 훈련 데이터 분석, 레벨 테스트 결과 집계, 사용자 행동 리서치 자동화에 확장 가능하다.
- 지금은 Gemini 기반 개인화 플랜과 결과 해석 단계에만 제한적으로 반영한다.

## 5. OMX 0.17.0 메모
- DESIGN.md + `$design` 워크플로를 canonical design path로 본다.
- Hermes MCP bridge는 세션 조정/보고용 안전 레일로 취급한다.
- plugin discovery가 더 강해졌더라도 이 저장소의 단일 진실 원천은 저장소 문서다.
- UltraQA식 적대적 검증 관점은 훈련 플로우 QA에도 유용하다.

## 채택하지 않은 것
- 전체 앱을 곧바로 Unity 중심 구조로 뒤집는 것
- 문서보다 도구 상태를 우선하는 것
- lockfile 없이 `npm install`로 임시 회피하는 것
