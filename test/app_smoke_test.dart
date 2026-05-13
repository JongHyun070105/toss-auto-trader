import 'package:batters_eye/app.dart';
import 'package:batters_eye/app_state.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('cold start walks through multi-slide onboarding before auth', (
    tester,
  ) async {
    await tester.pumpWidget(BattersEyeApp(store: BattersEyeStore.memory()));
    await tester.pumpAndSettle();

    expect(find.text('Batter’s Eye'), findsWidgets);
    expect(find.text('릴리스부터 읽는 감각'), findsOneWidget);
    expect(find.text('다음 설명'), findsOneWidget);
    expect(find.text('계정 화면으로 바로 가기'), findsOneWidget);

    await tester.tap(find.text('다음 설명'));
    await tester.pumpAndSettle();
    expect(find.text('지금 기준선을 먼저 확인'), findsOneWidget);

    await tester.tap(find.text('다음 설명'));
    await tester.pumpAndSettle();
    expect(find.text('AI 코치가 첫 7일을 정리'), findsOneWidget);
    expect(find.text('계정 만들고 시작하기'), findsOneWidget);

    await tester.tap(find.text('계정 만들고 시작하기'));
    await tester.pumpAndSettle();

    expect(find.text('회원가입'), findsOneWidget);
    expect(find.text('로그인'), findsOneWidget);
  });
}
