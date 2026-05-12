import 'package:flutter_test/flutter_test.dart';
import 'package:batters_eye/session.dart';

void main() {
  test('buildSession returns five rounds for a mode', () {
    final rounds = TrainingEngine.buildSession(TrainingMode.pitchType, seed: 7);

    expect(rounds, hasLength(5));
    expect(rounds.first.mode, TrainingMode.pitchType);
    expect(rounds.first.choices.length, 3);
    expect(rounds.first.prompt, isNotEmpty);
  });

  test('summarizeSession computes accuracy and average reaction time', () {
    final rounds = [
      const TrainingRound(
        id: 'r1',
        mode: TrainingMode.strikeZone,
        title: 'Low away fastball',
        prompt: '스트라이크인가?',
        choices: ['Strike', 'Ball'],
        correctIndex: 0,
        weaknessTag: 'low-away fastball',
        coachingPoint: '바깥쪽 낮은 공은 끝까지 보기.',
      ),
      const TrainingRound(
        id: 'r2',
        mode: TrainingMode.strikeZone,
        title: 'High heater',
        prompt: '스트라이크인가?',
        choices: ['Strike', 'Ball'],
        correctIndex: 1,
        weaknessTag: 'high heater',
        coachingPoint: '높은 공은 참는 습관을 확인.',
      ),
    ];

    final summary = TrainingSummary.fromAttempts(
      mode: TrainingMode.strikeZone,
      attempts: [
        RoundAttempt(
          round: rounds[0],
          selectedIndex: 0,
          reactionTime: const Duration(milliseconds: 420),
        ),
        RoundAttempt(
          round: rounds[1],
          selectedIndex: 0,
          reactionTime: const Duration(milliseconds: 540),
        ),
      ],
    );

    expect(summary.correctCount, 1);
    expect(summary.totalRounds, 2);
    expect(summary.accuracy, 0.5);
    expect(summary.averageReactionTime.inMilliseconds, 480);
    expect(summary.primaryWeakSpot, contains('high heater'));
  });
}
