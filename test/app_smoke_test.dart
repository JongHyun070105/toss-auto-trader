import 'package:batters_eye/app.dart';
import 'package:batters_eye/app_state.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('cold start shows the auth gate', (tester) async {
    await tester.pumpWidget(BattersEyeApp(store: BattersEyeStore.memory()));
    await tester.pumpAndSettle();

    expect(find.text('Batter’s Eye'), findsWidgets);
    expect(find.text('회원가입'), findsOneWidget);
    expect(find.text('로그인'), findsOneWidget);
    expect(find.text('계정부터 만들고, 프로필과 레벨을 쌓아가는 개인 훈련 루프.'), findsOneWidget);
  });
}
