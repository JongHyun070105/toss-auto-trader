import 'package:flutter/material.dart';

import 'app_copy.dart';
import 'app_state.dart';
import 'app_theme.dart';
import 'batters_eye_scope.dart';
import 'placement.dart';
import 'session.dart';
import 'settings_screen.dart';
import 'training_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  Future<void> _startMode(TrainingMode mode) async {
    final summary = await Navigator.of(context).push<TrainingSummary>(
      MaterialPageRoute(builder: (_) => TrainingScreen(mode: mode)),
    );

    if (!mounted || summary == null) return;

    final store = BattersEyeScope.of(context);
    await store.recordTrainingSummary(summary);
  }

  Future<void> _logout() => BattersEyeScope.of(context).logout();

  Future<void> _openSettings() async {
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const SettingsScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final copy = context.copy;
    final store = BattersEyeScope.of(context);
    final profile = store.profile;
    final placement = store.placementResult;
    final aiPlan = store.aiPlan;
    final lastReport = store.lastTrainingReport;
    final recommendedMode = store.recommendedMode;
    final level = placement?.level ?? PlacementLevel.rookie;

    return Scaffold(
      body: Container(
        decoration: BoxDecoration(gradient: context.pageGradient),
        child: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 28),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            copy.appTitle,
                            style: theme.textTheme.headlineLarge?.copyWith(
                              fontWeight: FontWeight.w900,
                              letterSpacing: -0.04,
                              color: context.textPrimary,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            copy.homeGreeting(store.displayName),
                            style: theme.textTheme.bodyLarge?.copyWith(
                              color: context.textSecondary,
                              height: 1.45,
                            ),
                          ),
                        ],
                      ),
                    ),
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        _SessionsBadge(count: store.completedSessionCount),
                        const SizedBox(width: 8),
                        IconButton.filledTonal(
                          onPressed: _openSettings,
                          icon: const Icon(Icons.settings_rounded),
                          tooltip: copy.settingsTooltip,
                        ),
                        const SizedBox(width: 8),
                        IconButton.filledTonal(
                          onPressed: _logout,
                          icon: const Icon(Icons.logout_rounded),
                          tooltip: copy.signOutTooltip,
                        ),
                      ],
                    ),
                  ],
                ),
                const SizedBox(height: 18),
                _HeroCard(
                  levelLabel: copy.placementLevelLabel(level),
                  blurb: aiPlan?.headline ??
                      (placement?.level != null
                          ? copy.placementLevelCoach(level)
                          : copy.heroFallbackBlurb),
                  recommendation: aiPlan?.focusSummary ??
                      (placement != null
                          ? copy.placementRecommendation(placement)
                          : copy.heroFallbackRecommendation),
                  actionLabel: copy.startModeLabel(recommendedMode),
                  onPressed: () => _startMode(recommendedMode),
                ),
                const SizedBox(height: 14),
                _PitchLabPreviewCard(
                  levelLabel: copy.placementLevelLabel(level),
                  mode: recommendedMode,
                  accuracyPercent: lastReport?.accuracyPercent,
                  reactionTimeMs:
                      lastReport?.averageReactionTime.inMilliseconds,
                  sessionCount: store.completedSessionCount,
                ),
                if (aiPlan != null) ...[
                  const SizedBox(height: 18),
                  _SectionHeader(
                    title: copy.homeAiSectionTitle,
                    subtitle: copy.homeAiSectionSubtitle,
                  ),
                  const SizedBox(height: 12),
                  _AiCoachCard(plan: aiPlan),
                ],
                const SizedBox(height: 18),
                _SectionHeader(
                  title: copy.profileSummary,
                  subtitle: copy.profileSubtitle,
                ),
                const SizedBox(height: 12),
                _ProfileCard(profile: profile),
                const SizedBox(height: 18),
                _SectionHeader(
                  title: copy.trainingModes,
                  subtitle: copy.trainingModesSubtitle,
                ),
                const SizedBox(height: 12),
                _ModeCard(
                  mode: TrainingMode.pitchType,
                  recommended: recommendedMode == TrainingMode.pitchType,
                  onTap: () => _startMode(TrainingMode.pitchType),
                ),
                const SizedBox(height: 12),
                _ModeCard(
                  mode: TrainingMode.strikeZone,
                  recommended: recommendedMode == TrainingMode.strikeZone,
                  onTap: () => _startMode(TrainingMode.strikeZone),
                ),
                const SizedBox(height: 12),
                _ModeCard(
                  mode: TrainingMode.swingDecision,
                  recommended: recommendedMode == TrainingMode.swingDecision,
                  onTap: () => _startMode(TrainingMode.swingDecision),
                ),
                const SizedBox(height: 18),
                _SectionHeader(
                  title: copy.latestReport,
                  subtitle: copy.latestReportSubtitle,
                ),
                const SizedBox(height: 12),
                _ReportCard(report: lastReport),
                const SizedBox(height: 18),
                _SectionHeader(
                  title: copy.howItWorks,
                  subtitle: copy.howItWorksSubtitle,
                ),
                const SizedBox(height: 12),
                const _HowItWorksCard(),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SessionsBadge extends StatelessWidget {
  const _SessionsBadge({required this.count});

  final int count;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: context.panelFill,
        border: Border.all(color: context.panelBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            copy.sessionsBadgeLabel,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: context.textMuted,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            '$count',
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w900),
          ),
        ],
      ),
    );
  }
}

class _HeroCard extends StatelessWidget {
  const _HeroCard({
    required this.levelLabel,
    required this.blurb,
    required this.recommendation,
    required this.actionLabel,
    required this.onPressed,
  });

  final String levelLabel;
  final String blurb;
  final String recommendation;
  final String actionLabel;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final copy = context.copy;
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF10233C), Color(0xFF162A4A), Color(0xFF0D1B31)],
        ),
        border: Border.all(color: context.panelBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _StatPill(label: copy.recommendedLevelLabel, value: levelLabel),
          const SizedBox(height: 14),
          Text(
            blurb,
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w900,
              letterSpacing: -0.03,
              color: Colors.white,
            ),
          ),
          const SizedBox(height: 10),
          Text(
            recommendation,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.72),
              height: 1.45,
            ),
          ),
          const SizedBox(height: 18),
          SizedBox(
            width: double.infinity,
            child: FilledButton(onPressed: onPressed, child: Text(actionLabel)),
          ),
        ],
      ),
    );
  }
}

class _AiCoachCard extends StatelessWidget {
  const _AiCoachCard({required this.plan});

  final AiTrainingPlan plan;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final theme = Theme.of(context);
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
            plan.headline,
            style: theme.textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.w900,
              letterSpacing: -0.03,
            ),
          ),
          const SizedBox(height: 10),
          _CoachLine(
            label: copy.aiPlanStrengthLabel,
            body: plan.strength,
          ),
          const SizedBox(height: 10),
          _CoachLine(
            label: copy.aiPlanRiskLabel,
            body: plan.risk,
          ),
          const SizedBox(height: 10),
          _CoachLine(
            label: copy.aiPlanWhyNowLabel,
            body: plan.whyNow,
          ),
        ],
      ),
    );
  }
}

class _CoachLine extends StatelessWidget {
  const _CoachLine({required this.label, required this.body});

  final String label;
  final String body;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: Theme.of(context).textTheme.labelLarge?.copyWith(
                fontWeight: FontWeight.w800,
                color: context.textMuted,
              ),
        ),
        const SizedBox(height: 4),
        Text(
          body,
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: context.textSecondary,
                height: 1.45,
              ),
        ),
      ],
    );
  }
}

class _PitchLabPreviewCard extends StatelessWidget {
  const _PitchLabPreviewCard({
    required this.levelLabel,
    required this.mode,
    required this.accuracyPercent,
    required this.reactionTimeMs,
    required this.sessionCount,
  });

  final String levelLabel;
  final TrainingMode mode;
  final int? accuracyPercent;
  final int? reactionTimeMs;
  final int sessionCount;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final copy = context.copy;
    final primary = theme.colorScheme.primary;
    final secondary = theme.colorScheme.secondary;
    final tertiary = theme.colorScheme.tertiary;
    final accuracy = accuracyPercent == null ? '—' : '$accuracyPercent%';
    final reaction = reactionTimeMs == null ? '—' : '${reactionTimeMs}ms';

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
          Row(
            children: [
              _StatPill(label: copy.pitchLab, value: copy.liveMapLabel),
              const SizedBox(width: 8),
              _StatPill(label: copy.level, value: levelLabel),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            copy.todayPitchMap,
            style: theme.textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.w900,
              letterSpacing: -0.03,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            copy.pitchMapSubtitle,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: context.textSecondary,
              height: 1.45,
            ),
          ),
          const SizedBox(height: 14),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(flex: 6, child: _StrikeZoneBoard(mode: mode)),
              const SizedBox(width: 12),
              Expanded(
                flex: 5,
                child: Column(
                  children: [
                    _MetricTile(label: copy.reportAccuracyLabel, value: accuracy, accent: primary),
                    const SizedBox(height: 10),
                    _MetricTile(
                      label: copy.reportReactionLabel,
                      value: reaction,
                      accent: secondary,
                    ),
                    const SizedBox(height: 10),
                    _MetricTile(
                      label: copy.sessions,
                      value: '$sessionCount',
                      accent: tertiary,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _StrikeZoneBoard extends StatelessWidget {
  const _StrikeZoneBoard({required this.mode});

  final TrainingMode mode;

  int get _highlightIndex => switch (mode) {
    TrainingMode.pitchType => 1,
    TrainingMode.strikeZone => 4,
    TrainingMode.swingDecision => 7,
  };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final copy = context.copy;
    final accent = theme.colorScheme.primary;
    final highlight = _highlightIndex;

    return AspectRatio(
      aspectRatio: 0.92,
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(22),
          gradient: const LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFF0D1C32), Color(0xFF122944), Color(0xFF0A1528)],
          ),
          border: Border.all(color: accent.withValues(alpha: 0.2)),
        ),
        child: Stack(
          children: [
            Positioned.fill(
              child: Column(
                children: List.generate(3, (row) {
                  return Expanded(
                    child: Row(
                      children: List.generate(3, (col) {
                        final index = row * 3 + col;
                        final isHot = index == highlight;
                        return Expanded(
                          child: Container(
                            margin: const EdgeInsets.all(4),
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(14),
                              color: isHot
                                  ? accent.withValues(alpha: 0.24)
                                  : Colors.white.withValues(alpha: 0.03),
                              border: Border.all(
                                color: isHot
                                    ? accent.withValues(alpha: 0.55)
                                    : Colors.white.withValues(alpha: 0.08),
                              ),
                            ),
                            child: isHot
                                ? Center(
                                    child: Container(
                                      width: 14,
                                      height: 14,
                                      decoration: BoxDecoration(
                                        shape: BoxShape.circle,
                                        color: Colors.white,
                                        boxShadow: [
                                          BoxShadow(
                                            color: accent.withValues(
                                              alpha: 0.5,
                                            ),
                                            blurRadius: 16,
                                            spreadRadius: 2,
                                          ),
                                        ],
                                      ),
                                    ),
                                  )
                                : null,
                          ),
                        );
                      }),
                    ),
                  );
                }),
              ),
            ),
            Positioned(
              left: 6,
              top: 4,
              right: 6,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    copy.strikeZoneLabel,
                    style: theme.textTheme.labelLarge?.copyWith(
                      color: Colors.white.withValues(alpha: 0.78),
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Align(
                    alignment: Alignment.centerRight,
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 6,
                      ),
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(999),
                        color: context.panelFill,
                        border: Border.all(
                          color: Colors.white.withValues(alpha: 0.08),
                        ),
                      ),
                      child: Text(
                        copy.trainingModeLabel(mode),
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: Colors.white,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            Positioned(
              left: 8,
              bottom: 8,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    copy.trainingModeFocus(mode),
                    style: theme.textTheme.labelLarge?.copyWith(
                      color: Colors.white.withValues(alpha: 0.82),
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    copy.trainingModeSubtitle(mode),
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: Colors.white.withValues(alpha: 0.58),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _MetricTile extends StatelessWidget {
  const _MetricTile({
    required this.label,
    required this.value,
    required this.accent,
  });

  final String label;
  final String value;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: accent.withValues(alpha: 0.11),
        border: Border.all(color: accent.withValues(alpha: 0.22)),
      ),
      child: Row(
        children: [
          Container(
            width: 10,
            height: 10,
            decoration: BoxDecoration(shape: BoxShape.circle, color: accent),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: context.textMuted,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  value,
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w900,
                    letterSpacing: -0.02,
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

class _ProfileCard extends StatelessWidget {
  const _ProfileCard({required this.profile});

  final UserProfile? profile;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final p = profile;

    if (p == null) {
      return _EmptyStateCard(
        title: copy.emptyProfileTitle,
        body: copy.emptyProfileBody,
      );
    }

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        color: context.panelFill,
        border: Border.all(color: context.panelBorder),
      ),
      child: Wrap(
        spacing: 10,
        runSpacing: 10,
        children: copy.profileChipTexts(p)
            .map(
              (chip) => Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 14,
                  vertical: 12,
                ),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(999),
                  color: context.panelSoftFill,
                  border: Border.all(
                    color: Colors.white.withValues(alpha: 0.08),
                  ),
                ),
                child: Text(
                  chip,
                  style: Theme.of(
                    context,
                  ).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
            )
            .toList(),
      ),
    );
  }
}

class _ModeCard extends StatelessWidget {
  const _ModeCard({
    required this.mode,
    required this.onTap,
    required this.recommended,
  });

  final TrainingMode mode;
  final VoidCallback onTap;
  final bool recommended;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final copy = context.copy;
    final accent = _accentForMode(mode);

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(24),
        child: Container(
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(24),
            color: context.panelFill,
            border: Border.all(
              color: recommended
                  ? accent.withValues(alpha: 0.55)
                  : Colors.white.withValues(alpha: 0.08),
            ),
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
                child: Icon(_iconForMode(mode), color: accent),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(
                          copy.trainingModeLabel(mode),
                          style: theme.textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        if (recommended) ...[
                          const SizedBox(width: 8),
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8,
                              vertical: 4,
                            ),
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(999),
                              color: accent.withValues(alpha: 0.16),
                            ),
                            child: Text(
                              copy.recommendedBadgeLabel,
                              style: theme.textTheme.labelSmall?.copyWith(
                                color: accent,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      copy.trainingModeHero(mode),
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: context.textSecondary,
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              const Icon(Icons.chevron_right_rounded, color: Colors.white54),
            ],
          ),
        ),
      ),
    );
  }
}

class _ReportCard extends StatelessWidget {
  const _ReportCard({required this.report});

  final TrainingReport? report;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    if (report == null) {
      return _EmptyStateCard(
        title: copy.emptyReportTitle,
        body: copy.emptyReportBody,
      );
    }

    final r = report!;
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
          Row(
            children: [
              _StatPill(label: copy.reportAccuracyLabel, value: '${r.accuracyPercent}%'),
              const SizedBox(width: 8),
              _StatPill(
                label: copy.reportReactionLabel,
                value: '${r.averageReactionTime.inMilliseconds}ms',
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            copy.trainingReportCoachLine(r),
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: context.textSecondary,
              height: 1.45,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '${copy.reportWeakSpotLabel}: ${copy.trainingRoundWeakSpot(r.primaryWeakSpot)}',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: context.textMuted,
            ),
          ),
        ],
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.title, required this.subtitle});

  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: Theme.of(
            context,
          ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 4),
        Text(
          subtitle,
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
            color: context.textMuted,
          ),
        ),
      ],
    );
  }
}

class _StatPill extends StatelessWidget {
  const _StatPill({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: context.panelFill,
        border: Border.all(color: context.panelBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: context.textMuted,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            value,
            style: Theme.of(
              context,
            ).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w800),
          ),
        ],
      ),
    );
  }
}

class _EmptyStateCard extends StatelessWidget {
  const _EmptyStateCard({required this.title, required this.body});

  final String title;
  final String body;

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
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
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

class _HowItWorksCard extends StatelessWidget {
  const _HowItWorksCard();

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
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
          _StepRow(
            number: '1',
            title: copy.howItWorksStep1Title,
            body: copy.howItWorksStep1Body,
          ),
          const SizedBox(height: 12),
          _StepRow(
            number: '2',
            title: copy.howItWorksStep2Title,
            body: copy.howItWorksStep2Body,
          ),
          const SizedBox(height: 12),
          _StepRow(
            number: '3',
            title: copy.howItWorksStep3Title,
            body: copy.howItWorksStep3Body,
          ),
        ],
      ),
    );
  }
}

class _StepRow extends StatelessWidget {
  const _StepRow({
    required this.number,
    required this.title,
    required this.body,
  });

  final String number;
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 28,
          height: 28,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: Colors.white.withValues(alpha: 0.08),
          ),
          child: Text(
            number,
            style: const TextStyle(fontWeight: FontWeight.w800),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: Theme.of(
                  context,
                ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 4),
              Text(
                body,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: context.textSecondary,
                  height: 1.45,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

Color _accentForMode(TrainingMode mode) {
  return switch (mode) {
    TrainingMode.pitchType => const Color(0xFF62E6FF),
    TrainingMode.strikeZone => const Color(0xFF84F58E),
    TrainingMode.swingDecision => const Color(0xFFFFCF72),
  };
}

IconData _iconForMode(TrainingMode mode) {
  return switch (mode) {
    TrainingMode.pitchType => Icons.sports_baseball_rounded,
    TrainingMode.strikeZone => Icons.center_focus_strong_rounded,
    TrainingMode.swingDecision => Icons.flash_on_rounded,
  };
}
