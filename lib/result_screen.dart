import 'package:flutter/material.dart';

import 'app_copy.dart';
import 'app_theme.dart';
import 'session.dart';

class ResultScreen extends StatelessWidget {
  const ResultScreen({super.key, required this.summary});

  final TrainingSummary summary;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final accuracy = (summary.accuracy * 100).round();
    final avg = summary.averageReactionTime.inMilliseconds;

    return Scaffold(
      appBar: AppBar(
        title: Text(copy.resultSessionComplete),
      ),
      body: Container(
        decoration: BoxDecoration(gradient: context.pageGradient),
        child: SafeArea(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
            children: [
              _ResultHero(summary: summary, accuracy: accuracy, avg: avg),
              const SizedBox(height: 14),
              Row(
                children: [
                  Expanded(
                    child: _MetricCard(
                      label: copy.resultAccuracyLabel,
                      value: '$accuracy%',
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _MetricCard(
                      label: copy.resultAvgReactionLabel,
                      value: '${avg}ms',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: _MetricCard(
                      label: copy.resultRoundsLabel,
                      value: '${summary.totalRounds}',
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _MetricCard(
                      label: copy.resultWeakSpotLabel,
                      value: copy.trainingRoundWeakSpot(summary.primaryWeakSpot),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 14),
              _InsightCard(summary: summary),
              const SizedBox(height: 14),
              _NextStepsCard(summary: summary),
              const SizedBox(height: 20),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  key: const ValueKey('backToDashboardButton'),
                  onPressed: () => Navigator.of(context).pop(summary),
                  child: Text(copy.resultBackToDashboard),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ResultHero extends StatelessWidget {
  const _ResultHero({
    required this.summary,
    required this.accuracy,
    required this.avg,
  });

  final TrainingSummary summary;
  final int accuracy;
  final int avg;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final accent = _accentForMode(summary.mode);

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(28),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [accent.withValues(alpha: 0.24), const Color(0xFF10233C)],
        ),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(999),
              color: accent.withValues(alpha: 0.16),
              border: Border.all(color: accent.withValues(alpha: 0.3)),
            ),
            child: Text(
              copy.trainingModeLabel(summary.mode),
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                color: accent,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
          const SizedBox(height: 14),
          Text(
            copy.resultSessionComplete,
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w900,
              letterSpacing: -0.03,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            copy.resultSessionLine(summary),
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.78),
              height: 1.45,
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: _HeroStat(value: '$accuracy%', label: copy.resultAccuracyLabel),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _HeroStat(value: '${avg}ms', label: copy.resultAvgReactionLabel),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _HeroStat(
                  value: copy.trainingRoundWeakSpot(summary.primaryWeakSpot),
                  label: copy.resultWeakSpotLabel,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _HeroStat extends StatelessWidget {
  const _HeroStat({required this.value, required this.label});

  final String value;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        color: Colors.white.withValues(alpha: 0.08),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: Colors.white70,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            value,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w900,
            ),
          ),
        ],
      ),
    );
  }
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
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
          const SizedBox(height: 6),
          Text(
            value,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }
}

class _InsightCard extends StatelessWidget {
  const _InsightCard({required this.summary});

  final TrainingSummary summary;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(26),
        color: context.panelFill,
        border: Border.all(color: context.panelBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            copy.resultCoachNote,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            copy.trainingSummaryEncouragement(summary),
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

class _NextStepsCard extends StatelessWidget {
  const _NextStepsCard({required this.summary});

  final TrainingSummary summary;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(26),
        color: context.panelSoftFill,
        border: Border.all(color: context.panelBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            copy.resultNextSteps,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            copy.resultNextStep(summary.mode),
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

Color _accentForMode(TrainingMode mode) {
  return switch (mode) {
    TrainingMode.pitchType => const Color(0xFF62E6FF),
    TrainingMode.strikeZone => const Color(0xFF84F58E),
    TrainingMode.swingDecision => const Color(0xFFFFCF72),
  };
}
