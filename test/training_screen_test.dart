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

    await tester.scrollUntilVisible(
      find.text('투구 시작'),
      250,
      scrollable: find.byType(Scrollable),
    );
    expect(find.text('투구 시작'), findsOneWidget);
    expect(find.text('릴리스'), findsOneWidget);
    expect(find.text('플레이트'), findsOneWidget);
    final ball = find.byKey(const ValueKey('pitchBall'));
    expect(ball, findsOneWidget);

    final initialCenter = tester.getCenter(ball);

    await tester.tap(find.text('투구 시작'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    final midCenter = tester.getCenter(ball);
    expect(midCenter.dy, isNot(equals(initialCenter.dy)));

    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('이 공의 구종은?'), findsOneWidget);
  });
}
