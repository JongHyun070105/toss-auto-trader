import 'package:flutter/material.dart';

import 'app_copy.dart';
import 'app_theme.dart';
import 'batters_eye_scope.dart';

class OnboardingIntroScreen extends StatefulWidget {
  const OnboardingIntroScreen({super.key});

  @override
  State<OnboardingIntroScreen> createState() => _OnboardingIntroScreenState();
}

class _OnboardingIntroScreenState extends State<OnboardingIntroScreen> {
  static const _totalSteps = 3;

  bool _submitting = false;
  int _currentStep = 0;

  bool get _isLastStep => _currentStep == _totalSteps - 1;

  Future<void> _advanceOrContinue() async {
    if (_submitting) return;
    if (!_isLastStep) {
      setState(() => _currentStep += 1);
      return;
    }
    await _continueToAuth();
  }

  Future<void> _continueToAuth() async {
    if (_submitting) return;
    setState(() => _submitting = true);
    await BattersEyeScope.of(context).markIntroSeen();
    if (!mounted) return;
    setState(() => _submitting = false);
  }

  void _goBack() {
    if (_submitting || _currentStep == 0) return;
    setState(() => _currentStep -= 1);
  }

  void _jumpToStep(int index) {
    if (_submitting || index == _currentStep) return;
    setState(() => _currentStep = index);
  }

  List<_IntroSlideData> _slides(AppCopy copy) => [
    _IntroSlideData(
      index: '01',
      title: copy.introStep1Title,
      body: copy.introStep1Body,
      metric: copy.introStep1Metric,
      icon: Icons.sports_baseball_rounded,
    ),
    _IntroSlideData(
      index: '02',
      title: copy.introStep2Title,
      body: copy.introStep2Body,
      metric: copy.introStep2Metric,
      icon: Icons.center_focus_strong_rounded,
    ),
    _IntroSlideData(
      index: '03',
      title: copy.introStep3Title,
      body: copy.introStep3Body,
      metric: copy.introStep3Metric,
      icon: Icons.auto_awesome_rounded,
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final copy = context.copy;
    final slides = _slides(copy);
    final slide = slides[_currentStep];

    return Scaffold(
      body: Container(
        decoration: BoxDecoration(gradient: context.pageGradient),
        child: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 28),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 8,
                        ),
                        decoration: BoxDecoration(
                          color: context.panelFill,
                          borderRadius: BorderRadius.circular(999),
                          border: Border.all(color: context.panelBorder),
                        ),
                        child: Text(
                          copy.introKicker,
                          style: theme.textTheme.labelLarge?.copyWith(
                            color: context.textSecondary,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    _CounterPill(
                      value: copy.introStepCounter(_currentStep + 1, slides.length),
                    ),
                  ],
                ),
                const SizedBox(height: 18),
                Text(
                  copy.appTitle,
                  style: theme.textTheme.headlineLarge?.copyWith(
                    fontWeight: FontWeight.w900,
                    letterSpacing: -0.04,
                    color: context.textPrimary,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  copy.introTitle,
                  style: theme.textTheme.headlineMedium?.copyWith(
                    fontWeight: FontWeight.w900,
                    letterSpacing: -0.03,
                    color: context.textPrimary,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  copy.introBody,
                  style: theme.textTheme.bodyLarge?.copyWith(
                    color: context.textSecondary,
                    height: 1.5,
                  ),
                ),
                const SizedBox(height: 22),
                Container(
                  padding: const EdgeInsets.all(22),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(28),
                    gradient: context.heroGradient,
                    border: Border.all(color: context.panelBorder),
                  ),
                  child: Column(
                    children: [
                      _IntroScene(step: _currentStep, icon: slide.icon),
                      const SizedBox(height: 18),
                      _IntroProgressStrip(
                        currentStep: _currentStep,
                        totalSteps: slides.length,
                      ),
                      const SizedBox(height: 18),
                      AnimatedSwitcher(
                        duration: const Duration(milliseconds: 220),
                        child: _ActiveIntroCard(
                          key: ValueKey(slide.index),
                          slide: slide,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    if (_currentStep > 0) ...[
                      OutlinedButton.icon(
                        onPressed: _submitting ? null : _goBack,
                        icon: const Icon(Icons.arrow_back_rounded),
                        label: Text(copy.introBackCta),
                      ),
                      const SizedBox(width: 10),
                    ],
                    Expanded(
                      child: FilledButton(
                        onPressed: _submitting ? null : _advanceOrContinue,
                        child: Text(
                          _isLastStep ? copy.introPrimaryCta : copy.introNextCta,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                TextButton(
                  onPressed: _submitting ? null : _continueToAuth,
                  child: Text(copy.introSecondaryCta),
                ),
                const SizedBox(height: 18),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    for (var i = 0; i < slides.length; i += 1)
                      SizedBox(
                        width: (MediaQuery.sizeOf(context).width - 50) / 3,
                        child: _IntroOverviewCard(
                          slide: slides[i],
                          active: i == _currentStep,
                          onTap: () => _jumpToStep(i),
                        ),
                      ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _IntroSlideData {
  const _IntroSlideData({
    required this.index,
    required this.title,
    required this.body,
    required this.metric,
    required this.icon,
  });

  final String index;
  final String title;
  final String body;
  final String metric;
  final IconData icon;
}

class _CounterPill extends StatelessWidget {
  const _CounterPill({required this.value});

  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: context.panelFill,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: context.panelBorder),
      ),
      child: Text(
        value,
        style: Theme.of(context).textTheme.labelLarge?.copyWith(
          color: context.textPrimary,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _IntroScene extends StatelessWidget {
  const _IntroScene({required this.step, required this.icon});

  final int step;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    return AspectRatio(
      aspectRatio: 1.55,
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(22),
          gradient: const LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFF0C1830), Color(0xFF132947), Color(0xFF0A1528)],
          ),
          border: Border.all(color: accent.withValues(alpha: 0.18)),
        ),
        child: Stack(
          children: [
            Positioned.fill(
              child: Padding(
                padding: const EdgeInsets.all(18),
                child: Row(
                  children: List.generate(3, (row) {
                    return Expanded(
                      child: Column(
                        children: List.generate(3, (col) {
                          final hot = (row == 1 && col == 1) ||
                              (step == 1 && row == 0 && col == 2) ||
                              (step == 2 && row == 2 && col == 0);
                          return Expanded(
                            child: Container(
                              margin: const EdgeInsets.all(5),
                              decoration: BoxDecoration(
                                borderRadius: BorderRadius.circular(14),
                                color: hot
                                    ? accent.withValues(alpha: 0.22)
                                    : Colors.white.withValues(alpha: 0.03),
                                border: Border.all(
                                  color: hot
                                      ? accent.withValues(alpha: 0.5)
                                      : Colors.white.withValues(alpha: 0.08),
                                ),
                              ),
                            ),
                          );
                        }),
                      ),
                    );
                  }),
                ),
              ),
            ),
            Positioned(
              left: 22,
              top: 18,
              child: Container(
                width: 14,
                height: 14,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: Colors.white,
                  boxShadow: [
                    BoxShadow(
                      color: accent.withValues(alpha: 0.5),
                      blurRadius: 18,
                      spreadRadius: 4,
                    ),
                  ],
                ),
              ),
            ),
            Positioned(
              left: 28,
              top: 24,
              child: Transform.rotate(
                angle: step == 0 ? -0.36 : (step == 1 ? -0.18 : -0.28),
                child: Container(
                  width: step == 2 ? 132 : 150,
                  height: 2.4,
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: [
                        Colors.white.withValues(alpha: 0.0),
                        Colors.white.withValues(alpha: 0.18),
                        accent.withValues(alpha: 0.88),
                      ],
                    ),
                  ),
                ),
              ),
            ),
            Positioned(
              right: 18,
              bottom: 18,
              child: Container(
                width: 56,
                height: 76,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: Colors.white.withValues(alpha: 0.18)),
                ),
              ),
            ),
            if (step == 1)
              Positioned(
                right: 18,
                top: 18,
                child: _SceneTag(
                  icon: Icons.timer_outlined,
                  label: '5Q',
                ),
              ),
            if (step == 2)
              Positioned(
                right: 18,
                top: 18,
                child: _SceneTag(
                  icon: Icons.auto_awesome_rounded,
                  label: 'AI',
                ),
              ),
            Positioned(
              left: 18,
              bottom: 18,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(16),
                  color: Colors.black.withValues(alpha: 0.24),
                  border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(icon, size: 16, color: accent),
                    const SizedBox(width: 8),
                    Text(
                      'STEP ${step + 1}',
                      style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SceneTag extends StatelessWidget {
  const _SceneTag({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.24),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 15, color: Theme.of(context).colorScheme.primary),
          const SizedBox(width: 6),
          Text(
            label,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: Colors.white,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }
}

class _IntroProgressStrip extends StatelessWidget {
  const _IntroProgressStrip({
    required this.currentStep,
    required this.totalSteps,
  });

  final int currentStep;
  final int totalSteps;

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    return Row(
      children: List.generate(totalSteps, (index) {
        final active = index <= currentStep;
        return Expanded(
          child: Container(
            margin: EdgeInsets.only(right: index == totalSteps - 1 ? 0 : 8),
            height: 6,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(999),
              color: active
                  ? accent.withValues(alpha: index == currentStep ? 0.90 : 0.42)
                  : Colors.white.withValues(alpha: 0.08),
            ),
          ),
        );
      }),
    );
  }
}

class _ActiveIntroCard extends StatelessWidget {
  const _ActiveIntroCard({super.key, required this.slide});

  final _IntroSlideData slide;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: context.panelFill,
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: context.panelBorder),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 44,
            height: 44,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: context.panelSoftFill,
              borderRadius: BorderRadius.circular(14),
            ),
            child: Text(
              slide.index,
              style: theme.textTheme.labelLarge?.copyWith(
                fontWeight: FontWeight.w900,
                color: theme.colorScheme.primary,
              ),
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  slide.title,
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  slide.body,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: context.textSecondary,
                    height: 1.45,
                  ),
                ),
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: context.panelSoftFill,
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    slide.metric,
                    style: theme.textTheme.labelLarge?.copyWith(
                      color: theme.colorScheme.primary,
                      fontWeight: FontWeight.w800,
                    ),
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

class _IntroOverviewCard extends StatelessWidget {
  const _IntroOverviewCard({
    required this.slide,
    required this.active,
    required this.onTap,
  });

  final _IntroSlideData slide;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: active ? context.panelFill : context.panelSoftFill,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(
              color: active
                  ? theme.colorScheme.primary.withValues(alpha: 0.26)
                  : context.panelBorder,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                slide.icon,
                size: 18,
                color: active ? theme.colorScheme.primary : context.textSecondary,
              ),
              const SizedBox(height: 12),
              Text(
                slide.index,
                style: theme.textTheme.labelMedium?.copyWith(
                  color: active ? theme.colorScheme.primary : context.textMuted,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                slide.title,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.bodyMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: context.textPrimary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
