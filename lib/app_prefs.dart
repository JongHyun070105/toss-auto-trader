import 'package:flutter/material.dart';

enum AppThemePreference { light, dark }

extension AppThemePreferenceX on AppThemePreference {
  ThemeMode get materialMode => switch (this) {
    AppThemePreference.light => ThemeMode.light,
    AppThemePreference.dark => ThemeMode.dark,
  };

  String get storageValue => name;

  static AppThemePreference fromStorage(String? value) {
    for (final preference in AppThemePreference.values) {
      if (preference.name == value) return preference;
    }
    return AppThemePreference.light;
  }
}

enum AppLanguage { korean, english }

extension AppLanguageX on AppLanguage {
  String get code => switch (this) {
    AppLanguage.korean => 'ko',
    AppLanguage.english => 'en',
  };

  Locale get locale => Locale(code);

  String get storageValue => name;

  static AppLanguage fromStorage(String? value) {
    for (final language in AppLanguage.values) {
      if (language.name == value) return language;
    }
    return AppLanguage.korean;
  }
}
