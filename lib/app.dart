import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'app_state.dart';
import 'app_theme.dart';
import 'batters_eye_scope.dart';
import 'onboarding_gate.dart';

class BattersEyeApp extends StatefulWidget {
  const BattersEyeApp({super.key, this.store});

  final BattersEyeStore? store;

  @override
  State<BattersEyeApp> createState() => _BattersEyeAppState();
}

class _BattersEyeAppState extends State<BattersEyeApp> {
  late final Future<BattersEyeStore> _storeFuture = widget.store != null
      ? Future.value(widget.store!)
      : BattersEyeStore.create();

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<BattersEyeStore>(
      future: _storeFuture,
      builder: (context, snapshot) {
        if (!snapshot.hasData) {
          return MaterialApp(
            debugShowCheckedModeBanner: false,
            title: 'Batter’s Eye',
            theme: buildBattersEyeLightTheme(),
            darkTheme: buildBattersEyeDarkTheme(),
            themeMode: ThemeMode.light,
            localizationsDelegates: const [
              GlobalMaterialLocalizations.delegate,
              GlobalWidgetsLocalizations.delegate,
              GlobalCupertinoLocalizations.delegate,
            ],
            supportedLocales: const [Locale('ko'), Locale('en')],
            home: const _LoadingScreen(),
          );
        }

        final store = snapshot.data!;
        return BattersEyeScope(
          store: store,
          child: AnimatedBuilder(
            animation: store,
            builder: (context, _) {
              return MaterialApp(
                debugShowCheckedModeBanner: false,
                title: 'Batter’s Eye',
                theme: buildBattersEyeLightTheme(),
                darkTheme: buildBattersEyeDarkTheme(),
                themeMode: store.themeMode,
                locale: store.locale,
                localizationsDelegates: const [
                  GlobalMaterialLocalizations.delegate,
                  GlobalWidgetsLocalizations.delegate,
                  GlobalCupertinoLocalizations.delegate,
                ],
                supportedLocales: const [Locale('ko'), Locale('en')],
                home: const OnboardingGate(),
              );
            },
          ),
        );
      },
    );
  }
}

class _LoadingScreen extends StatelessWidget {
  const _LoadingScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: BoxDecoration(gradient: context.pageGradient),
        child: const Center(child: CircularProgressIndicator()),
      ),
    );
  }
}
