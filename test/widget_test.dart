import 'package:batters_eye/app.dart';
import 'package:batters_eye/app_state.dart';
import 'package:batters_eye/placement.dart';
import 'package:batters_eye/session.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('dashboard shows personalized onboarding data', (tester) async {
    final email = 'minjun@example.com';
    final placement = PlacementEngine.evaluate([0, 1, 0, 1, 0]);
    final account = LocalAccount(
      email: email,
      passwordHash: BattersEyeStore.hashPassword(email, 'secret123'),
      profile: const UserProfile(
        name: '민준',
        age: 21,
        gender: '남성',
        position: '타자',
        battingSide: '우타',
        experience: '1~2년',
        goal: '구종 인식',
      ),
      placementResult: placement,
      lastTrainingReport: TrainingReport(
        mode: TrainingMode.pitchType,
        correctCount: 4,
        totalRounds: 5,
        averageReactionTime: Duration(milliseconds: 480),
        primaryWeakSpot: 'slider release',
        completedAt: DateTime(2026, 1, 1),
      ),
      completedSessionCount: 3,
    );

    final store = BattersEyeStore.memory(
      accounts: {email: account},
      currentEmail: email,
    );

    await tester.pumpWidget(BattersEyeApp(store: store));
    await tester.pumpAndSettle();

    expect(find.text('안녕, 민준님. 오늘의 루틴을 바로 시작하자.'), findsOneWidget);
    expect(find.text('Pitch Lab'), findsOneWidget);
    expect(find.textContaining('락인'), findsWidgets);
    expect(find.text('프로필 요약'), findsOneWidget);
    expect(find.text('Training modes'), findsOneWidget);
    expect(find.text('Latest report'), findsOneWidget);
    expect(find.text('80%'), findsAtLeastNWidgets(2));
  });
}
