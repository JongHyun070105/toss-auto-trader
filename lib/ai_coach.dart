import 'dart:convert';
import 'dart:io';

import 'app_prefs.dart';
import 'app_state.dart';
import 'placement.dart';
import 'session.dart';

const kGeminiModel = String.fromEnvironment(
  'GEMINI_MODEL',
  defaultValue: 'gemini-2.5-flash-lite',
);
const kGeminiApiKey = String.fromEnvironment('GEMINI_API_KEY');

class AiCoachPlanner {
  const AiCoachPlanner();

  Future<AiTrainingPlan> buildPlan({
    required AppLanguage language,
    required UserProfile profile,
    required PlacementResult placement,
    TrainingReport? lastReport,
  }) async {
    if (kGeminiApiKey.trim().isEmpty) {
      return _fallbackPlan(
        language: language,
        profile: profile,
        placement: placement,
        lastReport: lastReport,
      );
    }

    try {
      final responseText = await _requestGeminiPlan(
        language: language,
        profile: profile,
        placement: placement,
        lastReport: lastReport,
      );
      final parsed = _extractPlanFromGeminiResponse(responseText);
      if (parsed != null) return parsed;
    } catch (_) {
      // Fall back to local heuristic plan below.
    }

    return _fallbackPlan(
      language: language,
      profile: profile,
      placement: placement,
      lastReport: lastReport,
    );
  }

  Future<String> _requestGeminiPlan({
    required AppLanguage language,
    required UserProfile profile,
    required PlacementResult placement,
    TrainingReport? lastReport,
  }) async {
    final client = HttpClient();
    final uri = Uri.parse(
      'https://generativelanguage.googleapis.com/v1beta/models/$kGeminiModel:generateContent?key=$kGeminiApiKey',
    );

    final request = await client.postUrl(uri);
    request.headers.contentType = ContentType.json;
    request.write(
      jsonEncode({
        'contents': [
          {
            'parts': [
              {
                'text': _buildPrompt(
                  language: language,
                  profile: profile,
                  placement: placement,
                  lastReport: lastReport,
                ),
              },
            ],
          },
        ],
        'generationConfig': {
          'temperature': 0.6,
          'responseMimeType': 'application/json',
        },
      }),
    );

    final response = await request.close();
    final text = await response.transform(utf8.decoder).join();
    client.close(force: true);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw HttpException('Gemini request failed: ${response.statusCode}');
    }
    return text;
  }

  String _buildPrompt({
    required AppLanguage language,
    required UserProfile profile,
    required PlacementResult placement,
    TrainingReport? lastReport,
  }) {
    final isKo = language == AppLanguage.korean;
    final lastLine = lastReport == null
        ? (isKo
              ? '최근 훈련 기록은 아직 없음.'
              : 'No recent training report yet.')
        : (isKo
              ? '최근 훈련: ${_modeLabel(lastReport.mode, true)}, 정확도 ${lastReport.accuracyPercent}%, 평균 반응 ${lastReport.averageReactionTime.inMilliseconds}ms, 약점 ${lastReport.primaryWeakSpot}.'
              : 'Recent session: ${_modeLabel(lastReport.mode, false)}, accuracy ${lastReport.accuracyPercent}%, average reaction ${lastReport.averageReactionTime.inMilliseconds}ms, weak spot ${lastReport.primaryWeakSpot}.');

    return isKo
        ? '''너는 Batter's Eye의 개인 타격 코치다. 아래 사용자 정보를 보고 7일 훈련 플랜을 JSON으로만 반환해.

JSON schema:
{
  "headline": string,
  "strength": string,
  "risk": string,
  "focusSummary": string,
  "whyNow": string,
  "sevenDayPlan": [string, string, string, string, string, string, string]
}

규칙:
- 모든 답변은 한국어
- 문장은 짧고 코치처럼 직접적으로
- 허세 금지, 측정 근거 중심
- sevenDayPlan은 Day 1 ~ Day 7에 해당하는 실제 훈련 행동

프로필:
- 이름: ${profile.name}
- 나이: ${profile.age}
- 성별: ${profile.gender}
- 포지션: ${profile.position}
- 타석: ${profile.battingSide}
- 경험: ${profile.experience}
- 목표: ${profile.goal}

레벨 테스트:
- 레벨: ${placement.level.label}
- 점수: ${placement.score}
- 추천 모드: ${_modeLabel(placement.recommendedMode, true)}

$lastLine
'''
        : '''You are Batter's Eye's hitting coach. Return JSON only.

JSON schema:
{
  "headline": string,
  "strength": string,
  "risk": string,
  "focusSummary": string,
  "whyNow": string,
  "sevenDayPlan": [string, string, string, string, string, string, string]
}

Rules:
- English only
- Short, direct coach tone
- Ground every recommendation in the data
- sevenDayPlan must contain concrete Day 1 to Day 7 training actions

Profile:
- Name: ${profile.name}
- Age: ${profile.age}
- Gender: ${profile.gender}
- Position: ${profile.position}
- Batting side: ${profile.battingSide}
- Experience: ${profile.experience}
- Goal: ${profile.goal}

Placement:
- Level: ${placement.level.label}
- Score: ${placement.score}
- Recommended mode: ${_modeLabel(placement.recommendedMode, false)}

$lastLine
''';
  }

  AiTrainingPlan? _extractPlanFromGeminiResponse(String raw) {
    final decoded = jsonDecode(raw) as Map<String, dynamic>;
    final candidates = decoded['candidates'];
    if (candidates is! List || candidates.isEmpty) return null;
    final content = candidates.first['content'];
    final parts = content is Map<String, dynamic> ? content['parts'] : null;
    if (parts is! List || parts.isEmpty) return null;
    final text = (parts.first['text'] as String?)?.trim();
    if (text == null || text.isEmpty) return null;

    final planJson = jsonDecode(text) as Map<String, dynamic>;
    return AiTrainingPlan(
      model: kGeminiModel,
      headline: (planJson['headline'] as String?) ?? '오늘 훈련 방향을 먼저 잡자.',
      strength: (planJson['strength'] as String?) ?? '강점 데이터가 부족해.',
      risk: (planJson['risk'] as String?) ?? '약점 데이터가 부족해.',
      focusSummary:
          (planJson['focusSummary'] as String?) ?? '짧은 세션으로 기준을 맞춘다.',
      whyNow: (planJson['whyNow'] as String?) ?? '지금은 기준 루틴부터 시작한다.',
      sevenDayPlan: ((planJson['sevenDayPlan'] as List?) ?? const <dynamic>[])
          .map((item) => item.toString())
          .where((item) => item.trim().isNotEmpty)
          .toList(),
      usedLiveModel: true,
      generatedAt: DateTime.now(),
    );
  }

  AiTrainingPlan _fallbackPlan({
    required AppLanguage language,
    required UserProfile profile,
    required PlacementResult placement,
    TrainingReport? lastReport,
  }) {
    final isKo = language == AppLanguage.korean;
    final mode = placement.recommendedMode;
    final modeLabel = _modeLabel(mode, isKo);
    final strength = isKo
        ? _strengthLineKo(placement)
        : _strengthLineEn(placement);
    final risk = isKo
        ? _riskLineKo(mode, profile.goal)
        : _riskLineEn(mode, profile.goal);
    final headline = isKo
        ? '${profile.name.isEmpty ? '오늘' : '${profile.name}님의 오늘'} 첫 포커스는 $modeLabel.'
        : '${profile.name.isEmpty ? 'Today' : '${profile.name}’s'} first focus is $modeLabel.';
    final focusSummary = isKo
        ? '${placement.level.label} 단계 기준으로 $modeLabel부터 짧게 반복한다.'
        : 'Start with short repetitions in $modeLabel at the ${placement.level.label} level.';
    final whyNow = isKo
        ? _whyNowKo(placement, lastReport)
        : _whyNowEn(placement, lastReport);

    return AiTrainingPlan(
      model: kGeminiModel,
      headline: headline,
      strength: strength,
      risk: risk,
      focusSummary: focusSummary,
      whyNow: whyNow,
      sevenDayPlan: isKo
          ? _sevenDayKo(mode, placement, lastReport)
          : _sevenDayEn(mode, placement, lastReport),
      usedLiveModel: false,
      generatedAt: DateTime.now(),
    );
  }

  String _modeLabel(TrainingMode mode, bool isKo) => switch (mode) {
    TrainingMode.pitchType => isKo ? '구종 읽기' : 'Pitch Read',
    TrainingMode.strikeZone => isKo ? '존 판정' : 'Strike Zone',
    TrainingMode.swingDecision => isKo ? '스윙 판단' : 'Swing Judge',
  };

  String _strengthLineKo(PlacementResult placement) {
    if (placement.score >= 80) return '기본 판정 기준이 이미 꽤 안정적이야.';
    if (placement.score >= 60) return '읽는 기준은 있고, 반복만 더하면 빨라질 수 있어.';
    return '기초부터 다시 쌓으면 빠르게 정리될 여지가 커.';
  }

  String _strengthLineEn(PlacementResult placement) {
    if (placement.score >= 80) return 'Your baseline judgment is already fairly stable.';
    if (placement.score >= 60) return 'You have a baseline read, and repetition can speed it up.';
    return 'There is plenty of room to clean up the fundamentals quickly.';
  }

  String _riskLineKo(TrainingMode mode, String goal) {
    final goalText = goal.trim().isEmpty ? '실전 판단' : goal;
    return switch (mode) {
      TrainingMode.pitchType => '$goalText보다 먼저 릴리스 구분이 흔들리면 전체 판단이 늦어진다.',
      TrainingMode.strikeZone => '존 경계 공에서 기준이 흔들리면 chase가 늘어날 수 있어.',
      TrainingMode.swingDecision => '카운트와 코스를 함께 읽지 못하면 스윙 기준이 무너질 수 있어.',
    };
  }

  String _riskLineEn(TrainingMode mode, String goal) {
    final goalText = goal.trim().isEmpty ? 'game-time decision making' : goal;
    return switch (mode) {
      TrainingMode.pitchType => 'If release recognition wobbles, every later read for $goalText slows down.',
      TrainingMode.strikeZone => 'If the edge-zone standard moves around, chase decisions will rise.',
      TrainingMode.swingDecision => 'If count and location are not read together, the swing standard breaks down.',
    };
  }

  String _whyNowKo(PlacementResult placement, TrainingReport? lastReport) {
    if (lastReport == null) {
      return '${placement.score}점 기준 초기 측정이 끝났으니 첫 1주 루틴을 가볍게 고정할 타이밍이야.';
    }
    return '최근 ${lastReport.accuracyPercent}% 정확도와 ${lastReport.averageReactionTime.inMilliseconds}ms 반응을 보면 지금은 ${lastReport.primaryWeakSpot}을 줄이는 주간 루틴이 맞아.';
  }

  String _whyNowEn(PlacementResult placement, TrainingReport? lastReport) {
    if (lastReport == null) {
      return 'The ${placement.score}-point baseline is enough to lock in a light first-week routine.';
    }
    return 'With ${lastReport.accuracyPercent}% accuracy and ${lastReport.averageReactionTime.inMilliseconds}ms reactions, this is the right week to narrow ${lastReport.primaryWeakSpot}.';
  }

  List<String> _sevenDayKo(
    TrainingMode mode,
    PlacementResult placement,
    TrainingReport? lastReport,
  ) {
    final modeLabel = _modeLabel(mode, true);
    return [
      'Day 1 · $modeLabel 5분. 속도보다 기준을 먼저 맞춘다.',
      'Day 2 · 전날 틀린 패턴만 다시 5분 반복한다.',
      'Day 3 · $modeLabel 7분. 첫 판단을 늦추지 않는다.',
      'Day 4 · 쉬운 공 2세트 + 어려운 공 1세트로 리듬을 섞는다.',
      'Day 5 · ${lastReport?.primaryWeakSpot ?? '약점 코스'}를 한 가지로 좁혀서 7분만 판다.',
      'Day 6 · 실제 타석처럼 한 번 보고 바로 누르는 템포로 진행한다.',
      'Day 7 · 결과를 다시 보고 다음 주 시작 모드를 재선정한다.',
    ];
  }

  List<String> _sevenDayEn(
    TrainingMode mode,
    PlacementResult placement,
    TrainingReport? lastReport,
  ) {
    final modeLabel = _modeLabel(mode, false);
    return [
      'Day 1 · 5 minutes of $modeLabel. Set the standard before chasing speed.',
      'Day 2 · Repeat only yesterday’s misses for 5 minutes.',
      'Day 3 · 7 minutes of $modeLabel. Do not delay the first read.',
      'Day 4 · Mix two easy sets with one hard set to change tempo.',
      'Day 5 · Narrow the session to ${lastReport?.primaryWeakSpot ?? 'one weak zone'} for 7 minutes.',
      'Day 6 · Run it at game tempo: one look, one decision.',
      'Day 7 · Review the result and reset the starting mode for next week.',
    ];
  }
}
