import 'package:flutter/material.dart';

ThemeData buildBattersEyeLightTheme() {
  const bg = Color(0xFFF6F9FD);
  const surface = Color(0xFFFFFFFF);
  const surfaceSoft = Color(0xFFF4F7FB);
  const primary = Color(0xFF10233C);
  const primarySoft = Color(0xFF12385F);
  const cyan = Color(0xFF2FAEE7);
  const amber = Color(0xFFD7A337);

  final scheme = ColorScheme.fromSeed(
    seedColor: primarySoft,
    brightness: Brightness.light,
    primary: primary,
    secondary: cyan,
    tertiary: amber,
    surface: surface,
    onPrimary: Colors.white,
    onSecondary: Colors.white,
    onTertiary: Colors.white,
    onSurface: const Color(0xFF0F1B2D),
  );

  return _buildBaseTheme(
    brightness: Brightness.light,
    scheme: scheme,
    scaffoldBackgroundColor: bg,
    cardColor: surface,
    cardBorderColor: const Color(0xFFD6DEEA),
    fillColor: surfaceSoft,
    appBarBackground: bg,
    appBarForeground: const Color(0xFF0F1B2D),
    snackBarBackground: const Color(0xFF0F1B2D),
    buttonBackground: primary,
    buttonForeground: Colors.white,
  ).copyWith(
    colorScheme: scheme.copyWith(secondary: cyan, tertiary: amber),
    dividerTheme: DividerThemeData(color: const Color(0xFFD9E1ED)),
    iconTheme: const IconThemeData(color: Color(0xFF0F1B2D)),
  );
}

ThemeData buildBattersEyeDarkTheme() {
  const bg = Color(0xFF06111F);
  const bg2 = Color(0xFF07111F);
  const surface = Color(0xFF10233C);
  const surface2 = Color(0xFF162A4A);
  const primary = Color(0xFF62E6FF);
  const mint = Color(0xFF84F58E);
  const amber = Color(0xFFFFCF72);

  final scheme = ColorScheme.fromSeed(
    seedColor: primary,
    brightness: Brightness.dark,
    primary: primary,
    secondary: mint,
    tertiary: amber,
    surface: surface,
    onPrimary: bg,
    onSecondary: bg,
    onTertiary: bg,
  );

  return _buildBaseTheme(
    brightness: Brightness.dark,
    scheme: scheme,
    scaffoldBackgroundColor: bg2,
    cardColor: Colors.white.withValues(alpha: 0.06),
    cardBorderColor: Colors.white.withValues(alpha: 0.08),
    fillColor: Colors.white.withValues(alpha: 0.05),
    appBarBackground: bg2,
    appBarForeground: Colors.white,
    snackBarBackground: surface2,
    buttonBackground: primary,
    buttonForeground: bg,
  ).copyWith(
    colorScheme: scheme,
    dividerTheme: DividerThemeData(color: Colors.white.withValues(alpha: 0.08)),
  );
}

ThemeData _buildBaseTheme({
  required Brightness brightness,
  required ColorScheme scheme,
  required Color scaffoldBackgroundColor,
  required Color cardColor,
  required Color cardBorderColor,
  required Color fillColor,
  required Color appBarBackground,
  required Color appBarForeground,
  required Color snackBarBackground,
  required Color buttonBackground,
  required Color buttonForeground,
}) {
  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: scaffoldBackgroundColor,
    appBarTheme: AppBarTheme(
      backgroundColor: appBarBackground,
      foregroundColor: appBarForeground,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      centerTitle: false,
    ),
    cardTheme: CardThemeData(
      color: cardColor,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: fillColor,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: BorderSide(color: cardBorderColor),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: BorderSide(color: cardBorderColor),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: BorderSide(color: scheme.primary, width: 1.2),
      ),
      labelStyle: TextStyle(
        color: brightness == Brightness.dark ? Colors.white70 : const Color(0xFF46566D),
      ),
      hintStyle: TextStyle(
        color: brightness == Brightness.dark ? Colors.white54 : const Color(0xFF5F7089),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: buttonBackground,
        foregroundColor: buttonForeground,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        textStyle: const TextStyle(fontWeight: FontWeight.w800),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: buttonBackground,
        foregroundColor: buttonForeground,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        textStyle: const TextStyle(fontWeight: FontWeight.w800),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: brightness == Brightness.dark
          ? Colors.white.withValues(alpha: 0.05)
          : const Color(0xFFF1F5FA),
      disabledColor: brightness == Brightness.dark
          ? Colors.white.withValues(alpha: 0.03)
          : const Color(0xFFE8EEF5),
      selectedColor: scheme.primary.withValues(alpha: brightness == Brightness.dark ? 0.18 : 0.12),
      secondarySelectedColor:
          scheme.primary.withValues(alpha: brightness == Brightness.dark ? 0.18 : 0.12),
      labelStyle: TextStyle(
        color: brightness == Brightness.dark ? Colors.white : const Color(0xFF0F1B2D),
      ),
      secondaryLabelStyle: TextStyle(
        color: buttonForeground,
        fontWeight: FontWeight.w800,
      ),
      side: BorderSide(color: cardBorderColor),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: brightness == Brightness.dark ? Colors.white : const Color(0xFF0F1B2D),
        side: BorderSide(color: cardBorderColor),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        textStyle: const TextStyle(fontWeight: FontWeight.w700),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: brightness == Brightness.dark ? Colors.white : const Color(0xFF0F1B2D),
        textStyle: const TextStyle(fontWeight: FontWeight.w700),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: snackBarBackground,
      contentTextStyle: const TextStyle(color: Colors.white),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      behavior: SnackBarBehavior.floating,
    ),
  );
}

extension BattersEyeThemeX on BuildContext {
  bool get isDarkMode => Theme.of(this).brightness == Brightness.dark;

  LinearGradient get pageGradient => isDarkMode
      ? const LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Color(0xFF07111F), Color(0xFF0B1730), Color(0xFF06111F)],
        )
      : const LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Color(0xFFF7FAFE), Color(0xFFF1F5FA), Color(0xFFEAF0F7)],
        );

  LinearGradient get heroGradient => isDarkMode
      ? const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF10233C), Color(0xFF162A4A), Color(0xFF0D1B31)],
        )
      : const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFFFFFFFF), Color(0xFFF7FAFE), Color(0xFFEAF0F7)],
        );

  Color get panelFill => isDarkMode ? Colors.white.withValues(alpha: 0.06) : Colors.white;
  Color get panelSoftFill => isDarkMode ? Colors.white.withValues(alpha: 0.05) : const Color(0xFFF4F7FB);
  Color get panelBorder => isDarkMode ? Colors.white.withValues(alpha: 0.08) : const Color(0xFFD6DEEA);
  Color get textPrimary => isDarkMode ? Colors.white : const Color(0xFF0F1B2D);
  Color get textSecondary => isDarkMode
      ? Colors.white.withValues(alpha: 0.72)
      : const Color(0xFF405066);
  Color get textMuted => isDarkMode
      ? Colors.white.withValues(alpha: 0.52)
      : const Color(0xFF5A6A81);
}
