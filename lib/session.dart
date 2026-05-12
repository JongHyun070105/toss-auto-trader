import 'dart:math';

enum TrainingMode { pitchType, strikeZone, swingDecision }

extension TrainingModeX on TrainingMode {
  String get title => switch (this) {
    TrainingMode.pitchType => 'Pitch Read',
    TrainingMode.strikeZone => 'Strike Zone',
    TrainingMode.swingDecision => 'Swing Judge',
  };

  String get label => title;

  String get subtitle => switch (this) {
    TrainingMode.pitchType => '구종을 빠르게 읽는 훈련',
    TrainingMode.strikeZone => '공이 존 안인지 바로 판단',
    TrainingMode.swingDecision => '칠 공인지 참을 공인지 판단',
  };

  String get heroBlurb => switch (this) {
    TrainingMode.pitchType => 'Fastball / Slider / Curve를 빠르게 분류해봐.',
    TrainingMode.strikeZone => '스트라이크인지 볼인지 빠르게 판정해봐.',
    TrainingMode.swingDecision => '카운트와 코스를 보고 스윙 여부를 고르자.',
  };

  String get focusArea => switch (this) {
    TrainingMode.pitchType => '구종 인식 속도',
    TrainingMode.strikeZone => '존 판정 정확도',
    TrainingMode.swingDecision => '스윙 디시전',
  };

  String get actionText => switch (this) {
    TrainingMode.pitchType => 'Pitch Read drill',
    TrainingMode.strikeZone => 'Strike Zone drill',
    TrainingMode.swingDecision => 'Swing Judge drill',
  };
}

class TrainingRound {
  const TrainingRound({
    required this.id,
    required this.mode,
    required this.title,
    required this.prompt,
    required this.choices,
    required this.correctIndex,
    required this.weaknessTag,
    required this.coachingPoint,
  }) : assert(correctIndex >= 0);

  final String id;
  final TrainingMode mode;
  final String title;
  final String prompt;
  final List<String> choices;
  final int correctIndex;
  final String weaknessTag;
  final String coachingPoint;

  String get correctChoice => choices[correctIndex];
}

class RoundAttempt {
  const RoundAttempt({
    required this.round,
    required this.selectedIndex,
    required this.reactionTime,
  });

  final TrainingRound round;
  final int selectedIndex;
  final Duration reactionTime;

  bool get isCorrect => selectedIndex == round.correctIndex;
  String get selectedChoice => round.choices[selectedIndex];
}

class TrainingSummary {
  const TrainingSummary({
    required this.mode,
    required this.attempts,
    required this.correctCount,
    required this.averageReactionTime,
    required this.primaryWeakSpot,
  });

  final TrainingMode mode;
  final List<RoundAttempt> attempts;
  final int correctCount;
  final Duration averageReactionTime;
  final String primaryWeakSpot;

  int get totalRounds => attempts.length;
  double get accuracy => totalRounds == 0 ? 0 : correctCount / totalRounds;

  String get encouragement {
    if (totalRounds == 0) return '훈련이 아직 시작되지 않았어.';
    if (accuracy >= 0.8) {
      return '좋아. 같은 감각으로 더 어려운 투구까지 확장해보자.';
    }
    return '다음 5분은 $primaryWeakSpot만 집중해서 다시 보자.';
  }

  factory TrainingSummary.fromAttempts({
    required TrainingMode mode,
    required List<RoundAttempt> attempts,
  }) {
    final correctCount = attempts.where((attempt) => attempt.isCorrect).length;
    final averageReactionTime = attempts.isEmpty
        ? Duration.zero
        : Duration(
            milliseconds:
                (attempts
                            .map(
                              (attempt) => attempt.reactionTime.inMilliseconds,
                            )
                            .reduce((a, b) => a + b) /
                        attempts.length)
                    .round(),
          );

    final wrongCounts = <String, int>{};
    for (final attempt in attempts.where((attempt) => !attempt.isCorrect)) {
      wrongCounts.update(
        attempt.round.weaknessTag,
        (value) => value + 1,
        ifAbsent: () => 1,
      );
    }

    final primaryWeakSpot = wrongCounts.isEmpty
        ? '${mode.focusArea}는 안정적이야.'
        : wrongCounts.entries.reduce((a, b) => a.value >= b.value ? a : b).key;

    return TrainingSummary(
      mode: mode,
      attempts: List.unmodifiable(attempts),
      correctCount: correctCount,
      averageReactionTime: averageReactionTime,
      primaryWeakSpot: primaryWeakSpot,
    );
  }
}

class TrainingEngine {
  static const int defaultRoundCount = 5;

  static List<TrainingRound> buildSession(
    TrainingMode mode, {
    int seed = 42,
    int roundCount = defaultRoundCount,
  }) {
    final deck = switch (mode) {
      TrainingMode.pitchType => _pitchTypeDeck,
      TrainingMode.strikeZone => _strikeZoneDeck,
      TrainingMode.swingDecision => _swingDecisionDeck,
    };

    final random = Random(seed + mode.index * 13);
    final shuffled = [...deck]..shuffle(random);
    final selected = shuffled.take(roundCount).toList(growable: false);

    return List.generate(selected.length, (index) {
      final item = selected[index];
      return TrainingRound(
        id: '${mode.name}-$index-${item.id}',
        mode: mode,
        title: item.title,
        prompt: item.prompt,
        choices: item.choices,
        correctIndex: item.correctIndex,
        weaknessTag: item.weaknessTag,
        coachingPoint: item.coachingPoint,
      );
    }, growable: false);
  }
}

class _DeckItem {
  const _DeckItem({
    required this.id,
    required this.title,
    required this.prompt,
    required this.choices,
    required this.correctIndex,
    required this.weaknessTag,
    required this.coachingPoint,
  });

  final String id;
  final String title;
  final String prompt;
  final List<String> choices;
  final int correctIndex;
  final String weaknessTag;
  final String coachingPoint;
}

const List<_DeckItem> _pitchTypeDeck = [
  _DeckItem(
    id: 'pitch-fastball-letters',
    title: 'RHP 96mph at the letters',
    prompt: '이 공의 구종은?',
    choices: ['Fastball', 'Slider', 'Curve'],
    correctIndex: 0,
    weaknessTag: 'high heater',
    coachingPoint: '높은 직구는 릴리스 직후부터 눈을 놓치지 않는 게 핵심이야.',
  ),
  _DeckItem(
    id: 'pitch-slider-away',
    title: 'Glove-side sweep away',
    prompt: '이 공의 구종은?',
    choices: ['Fastball', 'Slider', 'Curve'],
    correctIndex: 1,
    weaknessTag: 'late sweep',
    coachingPoint: '슬라이더는 마지막에 휘는 타이밍을 끝까지 따라가보자.',
  ),
  _DeckItem(
    id: 'pitch-curve-dropping',
    title: '12-6 breaker dropping hard',
    prompt: '이 공의 구종은?',
    choices: ['Fastball', 'Slider', 'Curve'],
    correctIndex: 2,
    weaknessTag: 'big breaker',
    coachingPoint: '커브는 초반에 팔 스피드만 보고 속지 말고 낙차를 확인해.',
  ),
  _DeckItem(
    id: 'pitch-heater-inside',
    title: 'Inside heater, chest high',
    prompt: '이 공의 구종은?',
    choices: ['Fastball', 'Slider', 'Curve'],
    correctIndex: 0,
    weaknessTag: 'inside heater',
    coachingPoint: '몸쪽 빠른 공은 시야가 흔들리니 시작점을 먼저 보자.',
  ),
  _DeckItem(
    id: 'pitch-backfoot',
    title: 'Back-foot breaker',
    prompt: '이 공의 구종은?',
    choices: ['Fastball', 'Slider', 'Curve'],
    correctIndex: 1,
    weaknessTag: 'back-foot breaker',
    coachingPoint: '발쪽으로 떨어지는 공은 끝까지 참는 훈련이 중요해.',
  ),
  _DeckItem(
    id: 'pitch-big-arc',
    title: 'Big rainbow arc',
    prompt: '이 공의 구종은?',
    choices: ['Fastball', 'Slider', 'Curve'],
    correctIndex: 2,
    weaknessTag: 'rainbow curve',
    coachingPoint: '곡선이 큰 공은 처음 속도보다 회전과 낙차를 같이 보자.',
  ),
];

const List<_DeckItem> _strikeZoneDeck = [
  _DeckItem(
    id: 'zone-high-tight',
    title: 'High and tight',
    prompt: '스트라이크일까?',
    choices: ['Strike', 'Ball'],
    correctIndex: 0,
    weaknessTag: 'high in-zone',
    coachingPoint: '몸쪽 높은 공은 생각보다 존 안에 들어올 수 있어.',
  ),
  _DeckItem(
    id: 'zone-low-away',
    title: 'Low away just off',
    prompt: '스트라이크일까?',
    choices: ['Strike', 'Ball'],
    correctIndex: 1,
    weaknessTag: 'low-away chase',
    coachingPoint: '낮고 바깥쪽 공은 마지막에 속기 쉬우니 참는 습관을 확인해.',
  ),
  _DeckItem(
    id: 'zone-middle-middle',
    title: 'Middle-middle heater',
    prompt: '스트라이크일까?',
    choices: ['Strike', 'Ball'],
    correctIndex: 0,
    weaknessTag: 'middle heater',
    coachingPoint: '가운데 공은 더 자신 있게 스트라이크로 잡아도 좋아.',
  ),
  _DeckItem(
    id: 'zone-backdoor',
    title: 'Backdoor edge',
    prompt: '스트라이크일까?',
    choices: ['Strike', 'Ball'],
    correctIndex: 0,
    weaknessTag: 'backdoor edge',
    coachingPoint: '끝에서 들어오는 공은 존에 걸리는 순간을 놓치지 말자.',
  ),
  _DeckItem(
    id: 'zone-bounce',
    title: 'Bouncer in the dirt',
    prompt: '스트라이크일까?',
    choices: ['Strike', 'Ball'],
    correctIndex: 1,
    weaknessTag: 'dirt chase',
    coachingPoint: '낮게 꺾여 떨어지는 공은 초반 릴리스만 보고 속지 말자.',
  ),
  _DeckItem(
    id: 'zone-letters-off',
    title: 'Letters that miss high',
    prompt: '스트라이크일까?',
    choices: ['Strike', 'Ball'],
    correctIndex: 1,
    weaknessTag: 'high miss',
    coachingPoint: '너무 높은 공은 마지막 위치를 보고 확실히 걸러내자.',
  ),
];

const List<_DeckItem> _swingDecisionDeck = [
  _DeckItem(
    id: 'swing-2-0-heater',
    title: '2-0 count, middle-in heater',
    prompt: '스윙할까?',
    choices: ['Swing', 'Take'],
    correctIndex: 0,
    weaknessTag: 'green light count',
    coachingPoint: '유리한 카운트에서는 자신 있게 스윙하는 연습이 필요해.',
  ),
  _DeckItem(
    id: 'swing-0-2-slider',
    title: '0-2 count, slider below zone',
    prompt: '스윙할까?',
    choices: ['Swing', 'Take'],
    correctIndex: 1,
    weaknessTag: 'chase pitch',
    coachingPoint: '투 스트라이크에서는 존 밖 공을 끝까지 참는 게 핵심이야.',
  ),
  _DeckItem(
    id: 'swing-3-1-fastball',
    title: '3-1 count, get-me-over fastball',
    prompt: '스윙할까?',
    choices: ['Swing', 'Take'],
    correctIndex: 0,
    weaknessTag: 'hitter count',
    coachingPoint: '좋은 카운트의 한가운데 공은 놓치면 아까워.',
  ),
  _DeckItem(
    id: 'swing-1-2-breaking',
    title: '1-2 count, breaking ball off the plate',
    prompt: '스윙할까?',
    choices: ['Swing', 'Take'],
    correctIndex: 1,
    weaknessTag: 'borderline chase',
    coachingPoint: '애매한 공은 존을 끝까지 확인한 뒤 결정하자.',
  ),
  _DeckItem(
    id: 'swing-belt-high',
    title: 'Belt-high heater',
    prompt: '스윙할까?',
    choices: ['Swing', 'Take'],
    correctIndex: 0,
    weaknessTag: 'belt-high attack',
    coachingPoint: '스트라이크 존 한복판은 공격적으로 가져가도 좋아.',
  ),
  _DeckItem(
    id: 'swing-buried-curve',
    title: 'Buried curveball',
    prompt: '스윙할까?',
    choices: ['Swing', 'Take'],
    correctIndex: 1,
    weaknessTag: 'buried breaker',
    coachingPoint: '바닥으로 떨어지는 공은 낚이지 않고 참는 습관을 만든다.',
  ),
];
