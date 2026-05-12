import 'package:batters_eye/placement.dart';
import 'package:batters_eye/session.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('placement engine recommends the top level for perfect answers', () {
    final result = PlacementEngine.evaluate([0, 1, 0, 1, 0]);

    expect(PlacementEngine.questions, hasLength(5));
    expect(result.correctCount, 5);
    expect(result.totalQuestions, 5);
    expect(result.score, 100);
    expect(result.level, PlacementLevel.lockedIn);
    expect(result.recommendedMode, TrainingMode.swingDecision);
    expect(result.recommendationLine, contains('레벨'));
  });

  test('placement engine shifts toward weak modes when answers miss', () {
    final result = PlacementEngine.evaluate([1, 0, 1, 0, 1]);

    expect(result.correctCount, 0);
    expect(result.level, PlacementLevel.rookie);
    expect(result.recommendedMode, isNotNull);
    expect(
      result.recommendationLine,
      contains(result.recommendedMode.focusArea),
    );
  });
}
