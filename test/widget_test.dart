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
      aiPlan: AiTrainingPlan(
        model: 'gemini-2.5-flash-lite',
        headline: '민준님의 오늘 첫 포커스는 구종 읽기.',
        strength: '기본 판정 기준이 안정적이야.',
        risk: '슬라이더 릴리스 구분이 아직 흔들릴 수 있어.',
        focusSummary: '이번 주는 구종 읽기 반응 속도를 먼저 줄인다.',
        whyNow: '레벨은 높지만 첫 리드 속도를 더 줄일 여지가 있어.',
        sevenDayPlan: const ['Day 1'],
        usedLiveModel: false,
        generatedAt: DateTime(2026, 1, 1),
      ),
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
      hasSeenIntro: true,
    );

    await tester.pumpWidget(BattersEyeApp(store: store));
    await tester.pumpAndSettle();

    expect(find.text('안녕, 민준님. 오늘의 루틴을 바로 시작하자.'), findsOneWidget);
    expect(find.text('피치 랩'), findsOneWidget);
    expect(find.textContaining('락인'), findsWidgets);
    expect(find.text('프로필 요약'), findsOneWidget);
    expect(find.text('훈련 모드'), findsOneWidget);
    expect(find.text('최근 리포트'), findsOneWidget);
    expect(find.text('80%'), findsAtLeastNWidgets(2));
  });
}
