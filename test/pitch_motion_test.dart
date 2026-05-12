import 'package:batters_eye/pitch_motion.dart';
import 'package:batters_eye/session.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('pitch motion samples a readable arc toward the plate', () {
    final round = TrainingRound(
      id: 'pitch-fastball-letters',
      mode: TrainingMode.pitchType,
      title: 'RHP 96mph at the letters',
      prompt: '이 공의 구종은?',
      choices: const ['Fastball', 'Slider', 'Curve'],
      correctIndex: 0,
      weaknessTag: 'high heater',
      coachingPoint: '높은 직구는 릴리스 직후부터 눈을 놓치지 않는 게 핵심이야.',
    );

    final motion = pitchMotionForRound(round);
    const size = Size(320, 360);

    final start = motion.samplePoint(size, 0);
    final mid = motion.samplePoint(size, 0.5);
    final end = motion.samplePoint(size, 1);

    expect(start.dy, lessThan(mid.dy));
    expect(mid.dy, lessThan(end.dy));
    expect((end.dx - size.width / 2).abs(), lessThan(60));
    expect(motion.ballRadius(1), greaterThan(motion.ballRadius(0)));
    expect(motion.revealAt, inExclusiveRange(0, 1));
  });
}
