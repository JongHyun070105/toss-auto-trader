import 'package:batters_eye/app_state.dart';
import 'package:batters_eye/placement.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'store progresses from intro to ai plan to dashboard and restores cleanly',
    () async {
      final store = BattersEyeStore.memory();

      expect(store.stage, OnboardingStage.intro);

      await store.markIntroSeen();
      expect(store.stage, OnboardingStage.auth);

      expect(await store.signUp('coach@example.com', 'secret123'), isNull);
      expect(store.stage, OnboardingStage.profile);

      expect(
        await store.saveProfile(
          const UserProfile(
            name: '민준',
            age: 21,
            gender: '남성',
            position: '타자',
            battingSide: '우타',
            experience: '1~2년',
            goal: '구종 인식',
          ),
        ),
        isNull,
      );
      expect(store.stage, OnboardingStage.placement);

      await store.savePlacement(PlacementEngine.evaluate([0, 1, 0, 1, 0]));
      expect(store.stage, OnboardingStage.aiPlan);
      expect(store.displayName, '민준');
      expect(store.placementLevel, PlacementLevel.lockedIn);

      await store.saveAiPlan(
        AiTrainingPlan(
          model: 'gemini-2.5-flash-lite',
          headline: '민준님의 첫 포커스는 스윙 판단.',
          strength: '기본 판정 기준이 안정적이야.',
          risk: '카운트와 코스를 함께 읽는 루틴이 더 필요해.',
          focusSummary: '이번 주는 스윙 판단을 짧게 반복한다.',
          whyNow: '레벨 테스트 후 첫 주 루틴을 고정할 타이밍이야.',
          sevenDayPlan: const ['Day 1'],
          usedLiveModel: false,
          generatedAt: DateTime(2026, 1, 1),
        ),
      );
      expect(store.stage, OnboardingStage.dashboard);

      final exported = store.exportJson();
      final restored = BattersEyeStore.memory();
      restored.restoreForTest(exported);

      expect(restored.stage, OnboardingStage.dashboard);
      expect(restored.displayName, '민준');
      expect(restored.placementLevel, PlacementLevel.lockedIn);
      expect(restored.aiPlan?.headline, '민준님의 첫 포커스는 스윙 판단.');
    },
  );
}
