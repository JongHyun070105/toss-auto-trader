import 'session.dart';

enum PlacementLevel { rookie, focused, gameReady, lockedIn }

extension PlacementLevelX on PlacementLevel {
  String get label => switch (this) {
    PlacementLevel.rookie => '루키',
    PlacementLevel.focused => '포커스',
    PlacementLevel.gameReady => '게임 레디',
    PlacementLevel.lockedIn => '락인',
  };

  String get coachLine => switch (this) {
    PlacementLevel.rookie => '기초 판정 루틴부터 차근차근 쌓자.',
    PlacementLevel.focused => '한 가지 약점을 좁혀서 매일 반복하자.',
    PlacementLevel.gameReady => '실전 감각은 좋아. 반응 속도를 더 줄이자.',
    PlacementLevel.lockedIn => '좋아. 어려운 공을 섞어도 기준을 유지하자.',
  };

  String get intensity => switch (this) {
    PlacementLevel.rookie => '하루 5분 · 정확도 우선',
    PlacementLevel.focused => '하루 7분 · 약점 반복',
    PlacementLevel.gameReady => '하루 10분 · 속도 강화',
    PlacementLevel.lockedIn => '하루 12분 · 실전 난도',
  };
}

class PlacementQuestion {
  const PlacementQuestion({
    required this.id,
    required this.mode,
    required this.title,
    required this.prompt,
    required this.choices,
    required this.correctIndex,
    required this.coachNote,
  });

  final String id;
  final TrainingMode mode;
  final String title;
  final String prompt;
  final List<String> choices;
  final int correctIndex;
  final String coachNote;

  String get correctChoice => choices[correctIndex];
}

class PlacementResult {
  const PlacementResult({
    required this.level,
    required this.score,
    required this.correctCount,
    required this.totalQuestions,
    required this.recommendedMode,
    required this.completedAt,
  });

  final PlacementLevel level;
  final int score;
  final int correctCount;
  final int totalQuestions;
  final TrainingMode recommendedMode;
  final DateTime completedAt;

  double get accuracy =>
      totalQuestions == 0 ? 0 : correctCount / totalQuestions;

  String get recommendationLine =>
      '${level.label} 레벨 · ${recommendedMode.focusArea}부터 시작하자.';

  Map<String, Object?> toJson() => {
    'level': level.name,
    'score': score,
    'correctCount': correctCount,
    'totalQuestions': totalQuestions,
    'recommendedMode': recommendedMode.name,
    'completedAt': completedAt.toIso8601String(),
  };

  factory PlacementResult.fromJson(Map<String, Object?> json) {
    final totalQuestions = _readInt(json['totalQuestions'], fallback: 0);
    final correctCount = _readInt(json['correctCount'], fallback: 0);
    return PlacementResult(
      level: _placementLevelFromName(json['level'] as String?),
      score: _readInt(
        json['score'],
        fallback: totalQuestions == 0
            ? 0
            : ((correctCount / totalQuestions) * 100).round(),
      ),
      correctCount: correctCount,
      totalQuestions: totalQuestions,
      recommendedMode: _trainingModeFromName(
        json['recommendedMode'] as String?,
      ),
      completedAt:
          DateTime.tryParse((json['completedAt'] as String?) ?? '') ??
          DateTime.fromMillisecondsSinceEpoch(0),
    );
  }
}

class PlacementEngine {
  const PlacementEngine._();

  static const List<PlacementQuestion> questions = [
    PlacementQuestion(
      id: 'release-fastball',
      mode: TrainingMode.pitchType,
      title: '릴리스가 빠르고 공이 떠오른다',
      prompt: '가장 가능성이 높은 구종은?',
      choices: ['Fastball', 'Slider', 'Curve'],
      correctIndex: 0,
      coachNote: '직구는 초반 궤적이 가장 곧고 빠르게 보인다.',
    ),
    PlacementQuestion(
      id: 'low-away-zone',
      mode: TrainingMode.strikeZone,
      title: '낮고 바깥쪽으로 살짝 빠지는 공',
      prompt: '존 안으로 볼까?',
      choices: ['Strike', 'Ball'],
      correctIndex: 1,
      coachNote: '낮은 바깥쪽은 끝에서 속기 쉬운 대표 chase 코스다.',
    ),
    PlacementQuestion(
      id: 'hitter-count',
      mode: TrainingMode.swingDecision,
      title: '3-1 카운트, 가운데 높은 직구',
      prompt: '이 상황의 기본 선택은?',
      choices: ['Swing', 'Take'],
      correctIndex: 0,
      coachNote: '유리한 카운트의 좋은 공은 과감하게 공격한다.',
    ),
    PlacementQuestion(
      id: 'breaking-dirt',
      mode: TrainingMode.swingDecision,
      title: '0-2 카운트, 바닥으로 떨어지는 변화구',
      prompt: '참아야 할까?',
      choices: ['Swing', 'Take'],
      correctIndex: 1,
      coachNote: '투 스트라이크에서도 바닥 공은 기준을 지켜야 한다.',
    ),
    PlacementQuestion(
      id: 'backdoor-edge',
      mode: TrainingMode.strikeZone,
      title: '바깥에서 안으로 걸치는 백도어 공',
      prompt: '판정은?',
      choices: ['Strike', 'Ball'],
      correctIndex: 0,
      coachNote: '끝에서 들어오는 공은 마지막 위치까지 본다.',
    ),
  ];

  static PlacementResult evaluate(
    List<int> selectedIndices, {
    DateTime? completedAt,
  }) {
    if (selectedIndices.length != questions.length) {
      throw ArgumentError.value(
        selectedIndices.length,
        'selectedIndices.length',
        'Placement requires ${questions.length} answers.',
      );
    }

    var correctCount = 0;
    final wrongByMode = <TrainingMode, int>{};

    for (var i = 0; i < questions.length; i += 1) {
      final question = questions[i];
      final selected = selectedIndices[i];
      if (selected == question.correctIndex) {
        correctCount += 1;
      } else {
        wrongByMode.update(
          question.mode,
          (value) => value + 1,
          ifAbsent: () => 1,
        );
      }
    }

    final score = ((correctCount / questions.length) * 100).round();
    final level = recommendLevel(correctCount, questions.length);
    final recommendedMode = _recommendMode(wrongByMode, level);

    return PlacementResult(
      level: level,
      score: score,
      correctCount: correctCount,
      totalQuestions: questions.length,
      recommendedMode: recommendedMode,
      completedAt: completedAt ?? DateTime.now(),
    );
  }

  static PlacementLevel recommendLevel(int correctCount, int totalQuestions) {
    if (totalQuestions <= 0) return PlacementLevel.rookie;
    final accuracy = correctCount / totalQuestions;
    if (accuracy >= 0.85) return PlacementLevel.lockedIn;
    if (accuracy >= 0.65) return PlacementLevel.gameReady;
    if (accuracy >= 0.4) return PlacementLevel.focused;
    return PlacementLevel.rookie;
  }

  static TrainingMode _recommendMode(
    Map<TrainingMode, int> wrongByMode,
    PlacementLevel level,
  ) {
    if (wrongByMode.isEmpty) return TrainingMode.swingDecision;

    final sorted = wrongByMode.entries.toList()
      ..sort((a, b) {
        final countCompare = b.value.compareTo(a.value);
        if (countCompare != 0) return countCompare;
        return a.key.index.compareTo(b.key.index);
      });

    if (level == PlacementLevel.rookie) return TrainingMode.strikeZone;
    return sorted.first.key;
  }
}

int _readInt(Object? value, {required int fallback}) {
  if (value is int) return value;
  if (value is num) return value.round();
  if (value is String) return int.tryParse(value) ?? fallback;
  return fallback;
}

PlacementLevel _placementLevelFromName(String? name) {
  return PlacementLevel.values.firstWhere(
    (level) => level.name == name,
    orElse: () => PlacementLevel.rookie,
  );
}

TrainingMode _trainingModeFromName(String? name) {
  return TrainingMode.values.firstWhere(
    (mode) => mode.name == name,
    orElse: () => TrainingMode.pitchType,
  );
}
