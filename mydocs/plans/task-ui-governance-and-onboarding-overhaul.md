# Task Plan

- Task slug: ui-governance-and-onboarding-overhaul
- Date: 2026-05-13
- Owner: Hermes Agent (orchestrator-first)
- Related files:
  - AGENTS.md
  - DESIGN.md
  - mydocs/README.md
  - mydocs/orders/20260513.md
  - mydocs/manual/hyper_waterfall.md
  - mydocs/manual/ai_workflow_inspirations.md
  - mydocs/_templates/task_plan.md
  - mydocs/_templates/stage_report.md
  - mydocs/_templates/final_report.md
  - lib/app_copy.dart
  - lib/onboarding_intro_screen.dart
  - lib/pitch_scene.dart
  - test/app_smoke_test.dart
  - test/training_screen_test.dart
- Goal:
  - AppsInToss식 칸반 운영 원칙을 이 저장소용 Hyper-Waterfall Lite에 반영한다.
  - onboarding intro를 멀티슬라이드 explanatory flow로 바꾸고 auth→profile→placement→AI plan 흐름의 첫 인상을 더 친절하게 만든다.
  - copy 톤을 "짧고 직접적이되 공손한 코치 톤"으로 재정의하고 공통 copy 레이어에 우선 반영한다.
  - pitch scene을 release/flight/plate가 더 분명하게 읽히는 faux-3D 프리미엄 장면으로 끌어올린다.
  - external reference audit(openai/skills, marketingskills, awesome-codex-subagents, Dimillian/Skills)를 문서에 기록하고 mirror/defer 원칙을 정한다.
- Non-goals:
  - 실제 Unity/SceneKit 렌더러 도입
  - 온보딩 이후 stage 구조 전체를 새 상태머신으로 재작성
  - 모든 화면 copy를 한 번에 완전 재작성
  - 외부 skill 저장소를 통째로 vendor/mirror
- Risks:
  - 문서와 구현이 어긋날 수 있음
  - onboarding copy 변경으로 기존 widget test가 깨질 수 있음
  - pitch scene 디테일 추가가 과도한 정보 밀도를 만들 수 있음
  - 지나친 공손함으로 코치 톤의 긴장감이 약해질 수 있음
- Acceptance criteria:
  - AGENTS.md / DESIGN.md / mydocs manual이 kanban lane, WIP, blocked, evidence, orchestrator-first 원칙을 반영한다.
  - onboarding intro가 3-step slide progression을 가지며 마지막 CTA로 auth stage에 진입한다.
  - 주요 onboarding/auth/placement/training/result copy가 더 친절하고 일관된 어조를 사용한다.
  - pitch scene에 release/plate/depth/speed cue가 추가되어 장면의 구체성이 올라간다.
  - 관련 widget tests / analyze가 통과한다.
- Planned stages:
  1. 문서/거버넌스 갱신 (kanban + reference audit + templates)
  2. onboarding/copy/scene TDD 테스트 추가
  3. Flutter 구현 반영
  4. analyze/tests 및 device verification
- Verification plan:
  - flutter test
  - flutter analyze
  - emulator screenshot review after run
  - graphify update . after code changes
- Approval needed before implementation?: no (user explicitly asked to continue through completion)
