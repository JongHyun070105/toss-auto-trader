import 'package:batters_eye/app.dart';
import 'package:batters_eye/app_state.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets(
    'placement screen waits for start pitch before revealing a question',
    (tester) async {
      final email = 'rookie@example.com';
      final store = BattersEyeStore.memory(
        accounts: {
          email: LocalAccount(
            email: email,
            passwordHash: BattersEyeStore.hashPassword(email, 'secret123'),
            profile: const UserProfile(
              name: '루키',
              age: 19,
              gender: '응답 안 함',
              position: '타자',
              battingSide: '우타',
              experience: '입문',
              goal: '구종 인식',
            ),
          ),
        },
        currentEmail: email,
      );

      await tester.pumpWidget(BattersEyeApp(store: store));
      await tester.pumpAndSettle();

      expect(find.text('레벨 테스트'), findsOneWidget);
      expect(find.text('Start pitch'), findsOneWidget);
      expect(find.textContaining('질문 1/5'), findsNothing);
      expect(find.text('가장 가능성이 높은 구종은?'), findsNothing);

      await tester.ensureVisible(find.text('Start pitch'));
      await tester.tap(find.text('Start pitch'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 700));

      expect(find.textContaining('질문 1/5'), findsOneWidget);
      expect(find.text('가장 가능성이 높은 구종은?'), findsOneWidget);
    },
  );
}
