import 'package:flutter/material.dart';

import 'app_state.dart';
import 'onboarding_gate.dart';
import 'placement.dart';
import 'session.dart';
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

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final store = BattersEyeScope.of(context);
    final profile = store.profile;
    final placement = store.placementResult;
    final lastReport = store.lastTrainingReport;
    final recommendedMode = store.recommendedMode;

    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [Color(0xFF07111F), Color(0xFF0B1730), Color(0xFF06111F)],
          ),
        ),
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
                            'Batter’s Eye',
                            style: theme.textTheme.headlineLarge?.copyWith(
                              fontWeight: FontWeight.w900,
                              letterSpacing: -0.04,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            '안녕, ${store.displayName}님. 오늘의 루틴을 바로 시작하자.',
                            style: theme.textTheme.bodyLarge?.copyWith(
                              color: Colors.white.withValues(alpha: 0.72),
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
                          onPressed: _logout,
                          icon: const Icon(Icons.logout_rounded),
                          tooltip: '로그아웃',
                        ),
                      ],
                    ),
                  ],
                ),
                const SizedBox(height: 18),
                _HeroCard(
                  levelLabel: placement?.level.label ?? 'Level 1 · 루키',
                  blurb:
                      placement?.level.coachLine ?? '레벨 테스트를 마치면 개인 난도가 맞춰진다.',
                  recommendation:
                      placement?.recommendationLine ??
                      '프로필과 테스트를 쌓으면 오늘의 추천이 더 정교해진다.',
                  actionLabel: 'Start ${recommendedMode.label}',
                  onPressed: () => _startMode(recommendedMode),
                ),
                const SizedBox(height: 14),
                _PitchLabPreviewCard(
                  levelLabel: placement?.level.label ?? '루키',
                  mode: recommendedMode,
                  accuracyPercent: lastReport?.accuracyPercent,
                  reactionTimeMs:
                      lastReport?.averageReactionTime.inMilliseconds,
                  sessionCount: store.completedSessionCount,
                ),
                const SizedBox(height: 18),
                _SectionHeader(
                  title: '프로필 요약',
                  subtitle: '이 정보가 추천 레벨과 훈련 톤을 맞춘다.',
                ),
                const SizedBox(height: 12),
                _ProfileCard(profile: profile),
                const SizedBox(height: 18),
                _SectionHeader(
                  title: 'Training modes',
                  subtitle: '레벨 테스트 결과를 바탕으로 오늘의 모드를 고른다.',
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
                  title: 'Latest report',
                  subtitle: '훈련 후 약점이 자동으로 기록된다.',
                ),
                const SizedBox(height: 12),
                _ReportCard(report: lastReport),
                const SizedBox(height: 18),
                _SectionHeader(
                  title: 'How it works',
                  subtitle: '짧고 반복 가능해야 매일 돌아온다.',
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
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: Colors.white.withValues(alpha: 0.06),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '세션',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: Colors.white.withValues(alpha: 0.55),
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
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF10233C), Color(0xFF162A4A), Color(0xFF0D1B31)],
        ),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _StatPill(label: '추천 레벨', value: levelLabel),
          const SizedBox(height: 14),
          Text(
            blurb,
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w900,
              letterSpacing: -0.03,
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
    final primary = theme.colorScheme.primary;
    final secondary = theme.colorScheme.secondary;
    final tertiary = theme.colorScheme.tertiary;
    final accuracy = accuracyPercent == null ? '—' : '$accuracyPercent%';
    final reaction = reactionTimeMs == null ? '—' : '${reactionTimeMs}ms';

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        color: Colors.white.withValues(alpha: 0.06),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _StatPill(label: 'Pitch Lab', value: '실전 맵'),
              const SizedBox(width: 8),
              _StatPill(label: '레벨', value: levelLabel),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            '오늘의 피치 맵',
            style: theme.textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.w900,
              letterSpacing: -0.03,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            '작은 존을 보고, 공의 길을 빠르게 읽는 감각을 쌓자.',
            style: theme.textTheme.bodyMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.72),
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
                    _MetricTile(label: '정확도', value: accuracy, accent: primary),
                    const SizedBox(height: 10),
                    _MetricTile(
                      label: '반응',
                      value: reaction,
                      accent: secondary,
                    ),
                    const SizedBox(height: 10),
                    _MetricTile(
                      label: '세션',
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
                    'Strike zone',
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
                        color: Colors.white.withValues(alpha: 0.06),
                        border: Border.all(
                          color: Colors.white.withValues(alpha: 0.08),
                        ),
                      ),
                      child: Text(
                        mode.label,
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
                    mode.focusArea,
                    style: theme.textTheme.labelLarge?.copyWith(
                      color: Colors.white.withValues(alpha: 0.82),
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    mode.subtitle,
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
                    color: Colors.white.withValues(alpha: 0.58),
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
    final p = profile;

    if (p == null) {
      return _EmptyStateCard(
        title: '아직 프로필이 없어',
        body: '프로필을 입력하면 나이·성별·포지션에 맞게 레벨과 루틴을 더 잘 추천할 수 있다.',
      );
    }

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        color: Colors.white.withValues(alpha: 0.06),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Wrap(
        spacing: 10,
        runSpacing: 10,
        children: p.chips
            .map(
              (chip) => Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 14,
                  vertical: 12,
                ),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(999),
                  color: Colors.white.withValues(alpha: 0.05),
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
            color: Colors.white.withValues(alpha: 0.06),
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
                          mode.label,
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
                              '추천',
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
                      mode.heroBlurb,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: Colors.white.withValues(alpha: 0.72),
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
    if (report == null) {
      return const _EmptyStateCard(
        title: '아직 세션이 없어',
        body: '훈련을 한 번 끝내면 정확도와 약점이 자동으로 기록된다.',
      );
    }

    final r = report!;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        color: Colors.white.withValues(alpha: 0.06),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _StatPill(label: '정확도', value: '${r.accuracyPercent}%'),
              const SizedBox(width: 8),
              _StatPill(
                label: '반응',
                value: '${r.averageReactionTime.inMilliseconds}ms',
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            r.coachLine,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.72),
              height: 1.45,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '약점: ${r.primaryWeakSpot}',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.58),
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
            color: Colors.white.withValues(alpha: 0.58),
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
        color: Colors.white.withValues(alpha: 0.06),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: Colors.white.withValues(alpha: 0.58),
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
        color: Colors.white.withValues(alpha: 0.06),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
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
              color: Colors.white.withValues(alpha: 0.72),
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
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        color: Colors.white.withValues(alpha: 0.06),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _StepRow(
            number: '1',
            title: '프로필',
            body: '나이·성별·포지션을 기록해 개인 기준을 만든다.',
          ),
          const SizedBox(height: 12),
          _StepRow(
            number: '2',
            title: '레벨 테스트',
            body: '한 문제씩 풀며 시작 난도와 추천 모드를 정한다.',
          ),
          const SizedBox(height: 12),
          _StepRow(
            number: '3',
            title: '반복 훈련',
            body: '짧은 세션을 쌓고 리포트로 약점을 좁힌다.',
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
                  color: Colors.white.withValues(alpha: 0.72),
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
