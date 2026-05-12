import 'package:batters_eye/app_state.dart';
import 'package:batters_eye/placement.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'store progresses from auth to dashboard and restores cleanly',
    () async {
      final store = BattersEyeStore.memory();

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
      expect(store.stage, OnboardingStage.dashboard);
      expect(store.displayName, '민준');
      expect(store.placementLevel, PlacementLevel.lockedIn);

      final exported = store.exportJson();
      final restored = BattersEyeStore.memory();
      restored.restoreForTest(exported);

      expect(restored.stage, OnboardingStage.dashboard);
      expect(restored.displayName, '민준');
      expect(restored.placementLevel, PlacementLevel.lockedIn);
    },
  );
}
