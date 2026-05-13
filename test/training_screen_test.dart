import 'package:batters_eye/session.dart';
import 'package:batters_eye/training_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('training screen animates the pitch ball across the lane', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(home: TrainingScreen(mode: TrainingMode.pitchType)),
    );
    await tester.pumpAndSettle();

    for (var i = 0; i < 4 && find.byKey(const ValueKey('startPitchButton')).evaluate().isEmpty; i++) {
      await tester.drag(find.byType(Scrollable), const Offset(0, -420));
      await tester.pumpAndSettle();
    }
    expect(find.byKey(const ValueKey('startPitchButton')), findsOneWidget);
    expect(find.text('릴리스'), findsOneWidget);
    expect(find.text('플레이트'), findsOneWidget);
    expect(find.text('체감 구속'), findsOneWidget);
    expect(find.text('판단 창'), findsOneWidget);
    expect(find.textContaining('비행 라인'), findsOneWidget);
    final ball = find.byKey(const ValueKey('pitchBall'));
    expect(ball, findsOneWidget);

    final initialCenter = tester.getCenter(ball);

    await tester.tap(find.byKey(const ValueKey('startPitchButton')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    final midCenter = tester.getCenter(ball);
    expect(midCenter.dy, isNot(equals(initialCenter.dy)));

    await tester.pump(const Duration(milliseconds: 1000));
    expect(find.text('이 공의 구종은?'), findsOneWidget);
  });
}
