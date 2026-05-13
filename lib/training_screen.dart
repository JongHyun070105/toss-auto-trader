import 'dart:async';

import 'package:flutter/material.dart';

import 'app_copy.dart';
import 'app_theme.dart';
import 'pitch_scene.dart';
import 'result_screen.dart';
import 'session.dart';

class TrainingScreen extends StatefulWidget {
  const TrainingScreen({super.key, required this.mode});

  final TrainingMode mode;

  @override
  State<TrainingScreen> createState() => _TrainingScreenState();
}

class _TrainingScreenState extends State<TrainingScreen>
    with TickerProviderStateMixin {
  late final List<TrainingRound> _rounds;
  late final AnimationController _pitchController;
  final List<RoundAttempt> _attempts = [];

  int _roundIndex = 0;
  bool _showPrompt = false;
  bool _answered = false;
  bool _finishing = false;
  int? _selectedIndex;
  DateTime? _promptShownAt;

  TrainingRound get _currentRound => _rounds[_roundIndex];
  bool get _isLastRound => _roundIndex == _rounds.length - 1;
  PitchMotionSpec get _motion => pitchMotionForRound(_currentRound);

  @override
  void initState() {
    super.initState();
    _rounds = TrainingEngine.buildSession(widget.mode);
    _pitchController = AnimationController(vsync: this)
      ..addListener(_handlePitchTick);
  }

  @override
  void dispose() {
    _pitchController.dispose();
    super.dispose();
  }

  void _handlePitchTick() {
    if (_showPrompt || _answered || !mounted) return;
    if (_pitchController.value >= _motion.revealAt) {
      setState(() {
        _showPrompt = true;
        _promptShownAt = DateTime.now();
      });
    }
  }

  void _startPitch() {
    if (_showPrompt || _answered) return;

    setState(() {
      _showPrompt = false;
      _promptShownAt = null;
    });

    _pitchController.duration = _motion.duration;
    _pitchController.forward(from: 0);
  }

  void _chooseAnswer(int index) {
    if (!_showPrompt || _answered || _promptShownAt == null) return;

    final reactionTime = DateTime.now().difference(_promptShownAt!);

    setState(() {
      _answered = true;
      _selectedIndex = index;
      _attempts.add(
        RoundAttempt(
          round: _currentRound,
          selectedIndex: index,
          reactionTime: reactionTime,
        ),
      );
    });
  }

  Future<void> _nextRound() async {
    if (_finishing) return;

    if (!_isLastRound) {
      setState(() {
        _roundIndex += 1;
        _pitchController.stop();
        _pitchController.value = 0;
        _showPrompt = false;
        _answered = false;
        _selectedIndex = null;
        _promptShownAt = null;
      });
      return;
    }

    _finishing = true;
    final summary = TrainingSummary.fromAttempts(
      mode: widget.mode,
      attempts: _attempts,
    );

    final result = await Navigator.of(context).push<TrainingSummary>(
      MaterialPageRoute(builder: (_) => ResultScreen(summary: summary)),
    );

    if (!mounted) return;
    Navigator.of(context).pop(result ?? summary);
  }

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final progress = (_roundIndex + 1) / _rounds.length;
    final answeredCount = _attempts.length;
    final accuracy = answeredCount == 0
        ? 0.0
        : _attempts.where((attempt) => attempt.isCorrect).length /
            answeredCount;

    return Scaffold(
      appBar: AppBar(
        title: Text(
          copy.trainingAppBarTitle(
            widget.mode,
            _roundIndex + 1,
            _rounds.length,
          ),
        ),
      ),
      body: Container(
        decoration: BoxDecoration(gradient: context.pageGradient),
        child: SafeArea(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
            children: [
              _HeaderCard(
                mode: widget.mode,
                currentRound: _currentRound,
                progress: progress,
                answeredCount: answeredCount,
                totalCount: _rounds.length,
                accuracy: accuracy,
              ),
              const SizedBox(height: 16),
              AnimatedBuilder(
                animation: _pitchController,
                builder: (context, _) {
                  return PitchScene(
                    round: _currentRound,
                    motion: _motion,
                    progress: _pitchController.value,
                    promptVisible: _showPrompt,
                    answered: _answered,
                    selectedIndex: _selectedIndex,
                  );
                },
              ),
              const SizedBox(height: 16),
              AnimatedSwitcher(
                duration: const Duration(milliseconds: 220),
                child: _showPrompt
                    ? _PromptCard(
                        key: const ValueKey('prompt-shown'),
                        round: _currentRound,
                        selectedIndex: _selectedIndex,
                        answered: _answered,
                        onTapChoice: _chooseAnswer,
                      )
                    : _ReadyCard(
                        key: const ValueKey('prompt-hidden'),
                        mode: widget.mode,
                        onStart: _startPitch,
                      ),
              ),
              if (_answered) ...[
                const SizedBox(height: 14),
                _FeedbackCard(
                  isCorrect: _selectedIndex == _currentRound.correctIndex,
                  currentRound: _currentRound,
                  onNext: _nextRound,
                  isLastRound: _isLastRound,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _HeaderCard extends StatelessWidget {
  const _HeaderCard({
    required this.mode,
    required this.currentRound,
    required this.progress,
    required this.answeredCount,
    required this.totalCount,
    required this.accuracy,
  });

  final TrainingMode mode;
  final TrainingRound currentRound;
  final double progress;
  final int answeredCount;
  final int totalCount;
  final double accuracy;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final theme = Theme.of(context);
    final accent = _accentForMode(mode);

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(28),
        color: context.panelFill,
        border: Border.all(color: context.panelBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _HeaderPill(
                icon: _iconForMode(mode),
                label: copy.trainingModeLabel(mode),
                accent: accent,
              ),
              const Spacer(),
              _HeaderMetric(
                label: copy.trainingAccuracyLabel,
                value: '${(accuracy * 100).round()}%',
              ),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            copy.trainingRoundTitle(currentRound),
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w900,
              letterSpacing: -0.03,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            copy.trainingHeaderLine(mode),
            style: theme.textTheme.bodyMedium?.copyWith(
              color: context.textSecondary,
              height: 1.45,
            ),
          ),
          const SizedBox(height: 16),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              minHeight: 10,
              value: progress,
              backgroundColor: context.panelSoftFill,
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: _StatChip(
                  label: copy.trainingAnsweredLabel,
                  value: '$answeredCount/$totalCount',
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _StatChip(
                  label: copy.trainingFocusLabel,
                  value: copy.trainingModeFocus(mode),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ReadyCard extends StatelessWidget {
  const _ReadyCard({
    super.key,
    required this.mode,
    required this.onStart,
  });

  final TrainingMode mode;
  final VoidCallback onStart;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final theme = Theme.of(context);

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
            copy.trainingModeHero(mode),
            style: theme.textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            copy.trainingTrackReleaseHint,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: context.textSecondary,
              height: 1.45,
            ),
          ),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              key: const ValueKey('startPitchButton'),
              onPressed: onStart,
              icon: const Icon(Icons.play_arrow_rounded),
              label: Text(copy.trainingActionReady),
            ),
          ),
        ],
      ),
    );
  }
}

class _PromptCard extends StatelessWidget {
  const _PromptCard({
    super.key,
    required this.round,
    required this.selectedIndex,
    required this.answered,
    required this.onTapChoice,
  });

  final TrainingRound round;
  final int? selectedIndex;
  final bool answered;
  final ValueChanged<int> onTapChoice;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final theme = Theme.of(context);
    final choiceLabels = round.choices.map(copy.trainingChoiceLabel).toList();

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
            copy.trainingRoundPrompt(round),
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w900,
              letterSpacing: -0.03,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            copy.trainingPromptSupport,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: context.textSecondary,
            ),
          ),
          const SizedBox(height: 14),
          ...List.generate(
            choiceLabels.length,
            (index) => Padding(
              padding: EdgeInsets.only(
                bottom: index == choiceLabels.length - 1 ? 0 : 10,
              ),
              child: _ChoiceButton(
                label: choiceLabels[index],
                index: index,
                selected: selectedIndex == index,
                correct: answered && index == round.correctIndex,
                wrong:
                    answered && selectedIndex == index && index != round.correctIndex,
                enabled: !answered,
                onTap: () => onTapChoice(index),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ChoiceButton extends StatelessWidget {
  const _ChoiceButton({
    required this.label,
    required this.index,
    required this.selected,
    required this.correct,
    required this.wrong,
    required this.enabled,
    required this.onTap,
  });

  final String label;
  final int index;
  final bool selected;
  final bool correct;
  final bool wrong;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final background = correct
        ? scheme.secondary.withValues(alpha: 0.18)
        : wrong
        ? scheme.error.withValues(alpha: 0.18)
        : selected
        ? scheme.primary.withValues(alpha: 0.14)
        : context.panelSoftFill;
    final border = correct
        ? scheme.secondary
        : wrong
        ? scheme.error
        : selected
        ? scheme.primary
        : context.panelBorder;

    return InkWell(
      onTap: enabled ? onTap : null,
      borderRadius: BorderRadius.circular(20),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
        decoration: BoxDecoration(
          color: background,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: border),
        ),
        child: Row(
          children: [
            CircleAvatar(
              radius: 16,
              backgroundColor: border,
              child: Text(
                String.fromCharCode(65 + index),
                style: TextStyle(
                  color: border.computeLuminance() > 0.5 ? Colors.black : Colors.white,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                label,
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            if (correct)
              Icon(Icons.check_circle_rounded, color: scheme.secondary)
            else if (wrong)
              Icon(Icons.close_rounded, color: scheme.error),
          ],
        ),
      ),
    );
  }
}

class _FeedbackCard extends StatelessWidget {
  const _FeedbackCard({
    required this.isCorrect,
    required this.currentRound,
    required this.onNext,
    required this.isLastRound,
  });

  final bool isCorrect;
  final TrainingRound currentRound;
  final VoidCallback onNext;
  final bool isLastRound;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final theme = Theme.of(context);
    final color = isCorrect ? const Color(0xFF84F58E) : const Color(0xFFFF8FA3);

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(26),
        color: color.withValues(alpha: 0.14),
        border: Border.all(color: color.withValues(alpha: 0.32)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                isCorrect ? Icons.check_circle_rounded : Icons.error_rounded,
                color: color,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  copy.trainingFeedbackTitle(isCorrect),
                  style: theme.textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            copy.trainingCorrectAnswer(currentRound.correctChoice),
            style: theme.textTheme.bodyMedium?.copyWith(
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            copy.trainingRoundCoachNote(currentRound),
            style: theme.textTheme.bodyMedium?.copyWith(
              color: context.isDarkMode ? Colors.white.withValues(alpha: 0.82) : context.textPrimary,
              height: 1.45,
            ),
          ),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: onNext,
              child: Text(copy.trainingNextButton(isLastRound)),
            ),
          ),
        ],
      ),
    );
  }
}

class _HeaderPill extends StatelessWidget {
  const _HeaderPill({
    required this.icon,
    required this.label,
    required this.accent,
  });

  final IconData icon;
  final String label;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: accent.withValues(alpha: 0.14),
        border: Border.all(color: accent.withValues(alpha: 0.32)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: accent),
          const SizedBox(width: 8),
          Text(
            label,
            style: Theme.of(context).textTheme.labelLarge?.copyWith(
              color: accent,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }
}

class _HeaderMetric extends StatelessWidget {
  const _HeaderMetric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Text(
          label,
          style: Theme.of(context).textTheme.labelSmall?.copyWith(
            color: context.textMuted,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          value,
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
            fontWeight: FontWeight.w900,
          ),
        ),
      ],
    );
  }
}

class _StatChip extends StatelessWidget {
  const _StatChip({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: context.panelSoftFill,
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
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w800,
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

IconData _iconForMode(TrainingMode mode) {
  return switch (mode) {
    TrainingMode.pitchType => Icons.sports_baseball_rounded,
    TrainingMode.strikeZone => Icons.center_focus_strong_rounded,
    TrainingMode.swingDecision => Icons.bolt_rounded,
  };
}
