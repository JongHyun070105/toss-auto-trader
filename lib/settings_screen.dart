import 'package:flutter/material.dart';

import 'app_copy.dart';
import 'app_prefs.dart';
import 'app_theme.dart';
import 'batters_eye_scope.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final store = BattersEyeScope.of(context);
    final copy = context.copy;
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: Text(copy.settingsHeader),
      ),
      body: Container(
        decoration: BoxDecoration(gradient: context.pageGradient),
        child: SafeArea(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 28),
            children: [
              Text(
                copy.settingsHeader,
                style: theme.textTheme.headlineLarge?.copyWith(
                  fontWeight: FontWeight.w900,
                  letterSpacing: -0.04,
                  color: context.textPrimary,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                copy.settingsSubtitle,
                style: theme.textTheme.bodyLarge?.copyWith(
                  color: context.textSecondary,
                  height: 1.45,
                ),
              ),
              const SizedBox(height: 18),
              _SectionCard(
                title: copy.themeSection,
                subtitle: copy.themeSectionSubtitle,
                child: SegmentedButton<AppThemePreference>(
                  segments: [
                    ButtonSegment(
                      value: AppThemePreference.light,
                      label: Text(copy.lightThemeLabel),
                      icon: const Icon(Icons.light_mode_rounded),
                    ),
                    ButtonSegment(
                      value: AppThemePreference.dark,
                      label: Text(copy.darkThemeLabel),
                      icon: const Icon(Icons.dark_mode_rounded),
                    ),
                  ],
                  selected: {store.themePreference},
                  onSelectionChanged: (selection) {
                    if (selection.isEmpty) return;
                    store.setThemePreference(selection.first);
                  },
                ),
              ),
              const SizedBox(height: 12),
              _InfoCard(
                title: copy.lightThemeLabel,
                body: copy.lightThemeDescription,
                accent: theme.colorScheme.primary,
              ),
              const SizedBox(height: 12),
              _InfoCard(
                title: copy.darkThemeLabel,
                body: copy.darkThemeDescription,
                accent: theme.colorScheme.secondary,
              ),
              const SizedBox(height: 18),
              _SectionCard(
                title: copy.languageSection,
                subtitle: copy.languageDescription,
                child: SegmentedButton<AppLanguage>(
                  segments: [
                    ButtonSegment(
                      value: AppLanguage.korean,
                      label: Text(copy.koreanLanguageLabel),
                      icon: const Icon(Icons.language_rounded),
                    ),
                    ButtonSegment(
                      value: AppLanguage.english,
                      label: Text(copy.englishLanguageLabel),
                      icon: const Icon(Icons.translate_rounded),
                    ),
                  ],
                  selected: {store.language},
                  onSelectionChanged: (selection) {
                    if (selection.isEmpty) return;
                    store.setLanguage(selection.first);
                  },
                ),
              ),
              const SizedBox(height: 18),
              _PreviewCard(
                themeLabel: store.themePreference == AppThemePreference.dark
                    ? copy.darkThemeLabel
                    : copy.lightThemeLabel,
                languageLabel: store.language == AppLanguage.korean
                    ? copy.koreanLanguageLabel
                    : copy.englishLanguageLabel,
                accent: theme.colorScheme.primary,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SectionCard extends StatelessWidget {
  const _SectionCard({
    required this.title,
    required this.subtitle,
    required this.child,
  });

  final String title;
  final String subtitle;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        color: context.panelFill,
        border: Border.all(color: context.panelBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w800,
                  color: context.textPrimary,
                ),
          ),
          const SizedBox(height: 6),
          Text(
            subtitle,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: context.textSecondary,
                  height: 1.45,
                ),
          ),
          const SizedBox(height: 14),
          child,
        ],
      ),
    );
  }
}

class _InfoCard extends StatelessWidget {
  const _InfoCard({
    required this.title,
    required this.body,
    required this.accent,
  });

  final String title;
  final String body;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        color: accent.withValues(alpha: context.isDarkMode ? 0.12 : 0.08),
        border: Border.all(color: accent.withValues(alpha: 0.18)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w800,
                  color: context.textPrimary,
                ),
          ),
          const SizedBox(height: 6),
          Text(
            body,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: context.textSecondary,
                  height: 1.45,
                ),
          ),
        ],
      ),
    );
  }
}

class _PreviewCard extends StatelessWidget {
  const _PreviewCard({
    required this.themeLabel,
    required this.languageLabel,
    required this.accent,
  });

  final String themeLabel;
  final String languageLabel;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        gradient: context.heroGradient,
        border: Border.all(color: context.panelBorder),
      ),
      child: Row(
        children: [
          Container(
            width: 52,
            height: 52,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: accent.withValues(alpha: 0.16),
            ),
            child: Icon(Icons.tune_rounded, color: accent),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  copy.settingsPreviewLabel,
                  style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        color: context.textSecondary,
                        fontWeight: FontWeight.w700,
                      ),
                ),
                const SizedBox(height: 4),
                Text(
                  '$themeLabel · $languageLabel',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: context.textPrimary,
                        fontWeight: FontWeight.w800,
                      ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
