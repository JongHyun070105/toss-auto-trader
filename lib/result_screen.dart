import 'package:flutter/material.dart';

import 'session.dart';

class ResultScreen extends StatelessWidget {
  const ResultScreen({super.key, required this.summary});

  final TrainingSummary summary;

  @override
  Widget build(BuildContext context) {
    final accuracy = (summary.accuracy * 100).round();
    final avg = summary.averageReactionTime.inMilliseconds;

    return Scaffold(
      appBar: AppBar(title: Text('${summary.mode.title} report')),
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [Color(0xFF07111F), Color(0xFF0B1730), Color(0xFF07111F)],
          ),
        ),
        child: SafeArea(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
            children: [
              _ResultHero(summary: summary, accuracy: accuracy, avg: avg),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(
                    child: _MetricCard(label: 'Accuracy', value: '$accuracy%'),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _MetricCard(label: 'Avg RT', value: '${avg}ms'),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: _MetricCard(
                      label: 'Rounds',
                      value: '${summary.totalRounds}',
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _MetricCard(
                      label: 'Weak spot',
                      value: summary.primaryWeakSpot,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              _CoachCard(summary: summary),
              const SizedBox(height: 16),
              _NextStepsCard(summary: summary),
              const SizedBox(height: 20),
              FilledButton(
                key: const ValueKey('backToDashboardButton'),
                onPressed: () => Navigator.of(context).pop(summary),
                child: const Text('Back to dashboard'),
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
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(26),
        gradient: const LinearGradient(
          colors: [Color(0xFF10233C), Color(0xFF162A4A)],
        ),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Session complete',
            style: Theme.of(
              context,
            ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          Text(
            '이번 세션은 ${summary.mode.title} 중심으로 진행했고, 약한 지점을 바로 모았다.',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.74),
              height: 1.45,
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              _HeroStat(value: '$accuracy%', label: 'accuracy'),
              const SizedBox(width: 12),
              _HeroStat(value: '${avg}ms', label: 'avg reaction'),
              const SizedBox(width: 12),
              _HeroStat(value: summary.primaryWeakSpot, label: 'weak spot'),
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
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(18),
          color: Colors.white.withValues(alpha: 0.07),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: Theme.of(
                context,
              ).textTheme.labelSmall?.copyWith(color: Colors.white54),
            ),
            const SizedBox(height: 6),
            Text(
              value,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(
                context,
              ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
            ),
          ],
        ),
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
        color: Colors.white.withValues(alpha: 0.06),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: Theme.of(
              context,
            ).textTheme.labelSmall?.copyWith(color: Colors.white54),
          ),
          const SizedBox(height: 6),
          Text(
            value,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
          ),
        ],
      ),
    );
  }
}

class _CoachCard extends StatelessWidget {
  const _CoachCard({required this.summary});

  final TrainingSummary summary;

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
            'Coach note',
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          Text(
            summary.encouragement,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.74),
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
    final nextStep = switch (summary.mode) {
      TrainingMode.pitchType => '다음엔 더 빠른 직구와 느린 브레이킹볼을 섞어서 다시 읽어보자.',
      TrainingMode.strikeZone => '바깥쪽과 높은 공을 더 자주 섞어서 chase risk를 확인하자.',
      TrainingMode.swingDecision => '2-strike 상황을 늘려서 참아야 할 공을 더 많이 보자.',
    };

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
            'Next drill',
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          Text(
            nextStep,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.74),
              height: 1.45,
            ),
          ),
        ],
      ),
    );
  }
}
