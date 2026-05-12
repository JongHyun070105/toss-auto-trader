# Graph Report - batters_eye  (2026-05-12)

## Corpus Check
- 37 files · ~16,564 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 278 nodes · 288 edges · 26 communities (18 shown, 8 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]

## God Nodes (most connected - your core abstractions)
1. `package:flutter/material.dart` - 12 edges
2. `package:flutter_test/flutter_test.dart` - 8 edges
3. `session.dart` - 7 edges
4. `package:batters_eye/session.dart` - 5 edges
5. `onboarding_gate.dart` - 5 edges
6. `package:batters_eye/app_state.dart` - 4 edges
7. `app_state.dart` - 4 edges
8. `package:batters_eye/placement.dart` - 3 edges
9. `package:batters_eye/app.dart` - 3 edges
10. `RunnerTests` - 3 edges

## Surprising Connections (you probably didn't know these)
- None detected - all connections are within the same source files.

## Communities (26 total, 8 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (31): app.dart, app_state.dart, onboarding_gate.dart, package:flutter/material.dart, BattersEyeApp, _BattersEyeAppState, BattersEyeScope, build (+23 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (34): dart:ui, _accentForMode, ballRadius, _BallSeamPainter, build, _clamped, Color, Container (+26 more)

### Community 2 - "Community 2"
Cohesion: 0.07
Nodes (29): training_screen.dart, _accentForMode, AspectRatio, build, Column, Container, _EmptyStateCard, Expanded (+21 more)

### Community 3 - "Community 3"
Cohesion: 0.11
Nodes (18): package:batters_eye/app.dart, package:batters_eye/app_state.dart, package:batters_eye/pitch_motion.dart, package:batters_eye/placement.dart, package:batters_eye/session.dart, package:batters_eye/training_screen.dart, package:flutter_test/flutter_test.dart, main (+10 more)

### Community 4 - "Community 4"
Cohesion: 0.08
Nodes (24): dart:async, pitch_scene.dart, result_screen.dart, _accentForMode, build, _ChoiceButton, _chooseAnswer, Container (+16 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (22): _accentForMode, AspectRatio, build, Container, dispose, Expanded, Icon, _next (+14 more)

### Community 6 - "Community 6"
Cohesion: 0.1
Nodes (19): dart:convert, package:crypto/crypto.dart, package:flutter/foundation.dart, package:shared_preferences/shared_preferences.dart, placement.dart, BattersEyeStore, copyWith, exportJson (+11 more)

### Community 7 - "Community 7"
Cohesion: 0.17
Nodes (11): build, _CoachCard, Container, Expanded, _HeroStat, _MetricCard, _NextStepsCard, _ResultHero (+3 more)

### Community 8 - "Community 8"
Cohesion: 0.17
Nodes (11): auth_screen.dart, home_screen.dart, placement_screen.dart, profile_screen.dart, AnimatedSwitcher, BattersEyeScope, build, _LoadingScreen (+3 more)

### Community 9 - "Community 9"
Cohesion: 0.18
Nodes (10): session.dart, evaluate, PlacementEngine, _placementLevelFromName, PlacementQuestion, PlacementResult, _readInt, recommendLevel (+2 more)

### Community 10 - "Community 10"
Cohesion: 0.18
Nodes (10): Colors, Components, Do, Do’s and Don’ts, Don’t, Elevation & Depth, Layout & Spacing, Overview (+2 more)

### Community 11 - "Community 11"
Cohesion: 0.29
Nodes (6): dart:math, _DeckItem, RoundAttempt, TrainingEngine, TrainingRound, TrainingSummary

## Knowledge Gaps
- **217 isolated node(s):** `main`, `UserProfile`, `main`, `main`, `TrainingRound` (+212 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `package:flutter/material.dart` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 7`, `Community 8`?**
  _High betweenness centrality (0.388) - this node is a cross-community bridge._
- **Why does `session.dart` connect `Community 9` to `Community 1`, `Community 2`, `Community 4`, `Community 5`, `Community 6`, `Community 7`?**
  _High betweenness centrality (0.218) - this node is a cross-community bridge._
- **What connects `main`, `UserProfile`, `main` to the rest of the system?**
  _217 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.06 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.06 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.07 - nodes in this community are weakly interconnected._
- **Should `Community 3` be split into smaller, more focused modules?**
  _Cohesion score 0.11 - nodes in this community are weakly interconnected._