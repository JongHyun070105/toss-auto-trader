import 'package:flutter/material.dart';

import 'app_state.dart';
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
            theme: _buildTheme(),
            home: const _LoadingScreen(),
          );
        }

        final store = snapshot.data!;
        return BattersEyeScope(
          store: store,
          child: MaterialApp(
            debugShowCheckedModeBanner: false,
            title: 'Batter’s Eye',
            theme: _buildTheme(),
            home: const OnboardingGate(),
          ),
        );
      },
    );
  }

  ThemeData _buildTheme() {
    const bg950 = Color(0xFF06111F);
    const bg900 = Color(0xFF07111F);
    const surface800 = Color(0xFF10233C);
    const surface700 = Color(0xFF162A4A);
    const cyan = Color(0xFF62E6FF);
    const mint = Color(0xFF84F58E);
    const amber = Color(0xFFFFCF72);

    final scheme = ColorScheme.fromSeed(
      seedColor: cyan,
      brightness: Brightness.dark,
      primary: cyan,
      secondary: mint,
      tertiary: amber,
      surface: surface800,
      onPrimary: bg950,
      onSecondary: bg950,
      onTertiary: bg950,
    );

    final baseTheme = ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: scheme,
      scaffoldBackgroundColor: bg900,
      appBarTheme: const AppBarTheme(
        backgroundColor: bg900,
        foregroundColor: Colors.white,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        centerTitle: false,
      ),
      cardTheme: CardThemeData(
        color: Colors.white.withValues(alpha: 0.06),
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white.withValues(alpha: 0.05),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 16,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(18),
          borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.08)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(18),
          borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.08)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(18),
          borderSide: const BorderSide(color: cyan, width: 1.2),
        ),
        labelStyle: const TextStyle(color: Colors.white70),
        hintStyle: const TextStyle(color: Colors.white54),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: cyan,
          foregroundColor: bg950,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(18),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
          textStyle: const TextStyle(fontWeight: FontWeight.w800),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: cyan,
          foregroundColor: bg950,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(18),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
          textStyle: const TextStyle(fontWeight: FontWeight.w800),
        ),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: Colors.white.withValues(alpha: 0.05),
        disabledColor: Colors.white.withValues(alpha: 0.03),
        selectedColor: cyan.withValues(alpha: 0.18),
        secondarySelectedColor: cyan.withValues(alpha: 0.18),
        labelStyle: const TextStyle(color: Colors.white),
        secondaryLabelStyle: const TextStyle(
          color: bg950,
          fontWeight: FontWeight.w800,
        ),
        side: BorderSide(color: Colors.white.withValues(alpha: 0.08)),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: Colors.white,
          side: BorderSide(color: Colors.white.withValues(alpha: 0.16)),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(18),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
          textStyle: const TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: Colors.white,
          textStyle: const TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: surface700,
        contentTextStyle: const TextStyle(color: Colors.white),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        behavior: SnackBarBehavior.floating,
      ),
    );

    return baseTheme;
  }
}

class _LoadingScreen extends StatelessWidget {
  const _LoadingScreen();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: DecoratedBox(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [Color(0xFF07111F), Color(0xFF0B1730), Color(0xFF06111F)],
          ),
        ),
        child: Center(child: CircularProgressIndicator()),
      ),
    );
  }
}
