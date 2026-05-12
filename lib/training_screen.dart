import 'dart:async';

import 'package:flutter/material.dart';

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
    final progress = (_roundIndex + 1) / _rounds.length;
    final answeredCount = _attempts.length;
    final accuracy = answeredCount == 0
        ? 0.0
        : _attempts.where((attempt) => attempt.isCorrect).length /
            answeredCount;

    return Scaffold(
      appBar: AppBar(
        title: Text(
          '${widget.mode.title} · ${_roundIndex + 1}/${_rounds.length}',
        ),
      ),
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
              _HeaderCard(
                mode: widget.mode,
                progress: progress,
                answeredCount: answeredCount,
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
                    ? Column(
                        key: const ValueKey('prompt-shown'),
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            _currentRound.prompt,
                            style: Theme.of(context).textTheme.titleLarge
                                ?.copyWith(fontWeight: FontWeight.w800),
                          ),
                          const SizedBox(height: 12),
                          Wrap(
                            spacing: 12,
                            runSpacing: 12,
                            children: List.generate(
                              _currentRound.choices.length,
                              (index) => _ChoiceButton(
                                label: _currentRound.choices[index],
                                selected: _selectedIndex == index,
                                correct:
                                    _answered &&
                                    index == _currentRound.correctIndex,
                                wrong:
                                    _answered &&
                                    _selectedIndex == index &&
                                    index != _currentRound.correctIndex,
                                enabled: !_answered,
                                onTap: () => _chooseAnswer(index),
                              ),
                            ),
                          ),
                        ],
                      )
                    : Column(
                        key: const ValueKey('prompt-hidden'),
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          FilledButton.icon(
                            key: const ValueKey('startPitchButton'),
                            onPressed: _startPitch,
                            icon: const Icon(Icons.play_arrow_rounded),
                            label: const Text('Start pitch'),
                          ),
                          const SizedBox(height: 10),
                          Text(
                            '릴리스 직후 짧게 보고 답해봐. 반응 시간도 함께 측정된다.',
                            style: Theme.of(context).textTheme.bodyMedium
                                ?.copyWith(
                                  color: Colors.white.withValues(alpha: 0.72),
                                ),
                          ),
                        ],
                      ),
              ),
              const SizedBox(height: 16),
              if (_answered)
                _FeedbackCard(
                  isCorrect: _selectedIndex == _currentRound.correctIndex,
                  currentRound: _currentRound,
                  onNext: _nextRound,
                  isLastRound: _isLastRound,
                ),
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
    required this.progress,
    required this.answeredCount,
    required this.accuracy,
  });

  final TrainingMode mode;
  final double progress;
  final int answeredCount;
  final double accuracy;

  @override
  Widget build(BuildContext context) {
    final accent = _accentForMode(mode);

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        color: Colors.white.withValues(alpha: 0.05),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: accent.withValues(alpha: 0.14),
                  shape: BoxShape.circle,
                ),
                child: Icon(_iconForMode(mode), color: accent),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      mode.title,
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Track the pitch, make the read, then sharpen the loop.',
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: Colors.white.withValues(alpha: 0.72),
                      ),
                    ),
                  ],
                ),
              ),
              _StatChip(label: 'Focus', value: mode.focusArea),
            ],
          ),
          const SizedBox(height: 16),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              minHeight: 10,
              value: progress,
              backgroundColor: Colors.white.withValues(alpha: 0.08),
            ),
          ),
          const SizedBox(height: 10),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              _StatChip(label: 'Answered', value: '$answeredCount'),
              _StatChip(
                label: 'Accuracy',
                value: '${(accuracy * 100).round()}%',
              ),
              _StatChip(label: 'Focus', value: mode.focusArea),
            ],
          ),
        ],
      ),
    );
  }
}

class _ChoiceButton extends StatelessWidget {
  const _ChoiceButton({
    required this.label,
    required this.selected,
    required this.correct,
    required this.wrong,
    required this.enabled,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final bool correct;
  final bool wrong;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final background = correct
        ? const Color(0xFF84F58E).withValues(alpha: 0.18)
        : wrong
        ? const Color(0xFFFF8FA3).withValues(alpha: 0.18)
        : selected
        ? Colors.white.withValues(alpha: 0.12)
        : Colors.white.withValues(alpha: 0.06);
    final border = correct
        ? const Color(0xFF84F58E)
        : wrong
        ? const Color(0xFFFF8FA3)
        : Colors.white.withValues(alpha: 0.10);

    return SizedBox(
      width: 160,
      child: OutlinedButton(
        onPressed: enabled ? onTap : null,
        style: OutlinedButton.styleFrom(
          backgroundColor: background,
          side: BorderSide(color: border),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        ),
        child: Text(label, textAlign: TextAlign.center),
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
    final color = isCorrect ? const Color(0xFF84F58E) : const Color(0xFFFF8FA3);
    final title = isCorrect ? 'Good read' : 'Re-read that one';

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        color: color.withValues(alpha: 0.14),
        border: Border.all(color: color.withValues(alpha: 0.28)),
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
              Text(
                title,
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            'Correct answer: ${currentRound.correctChoice}',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            currentRound.coachingPoint,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.78),
              height: 1.45,
            ),
          ),
          const SizedBox(height: 14),
          FilledButton(
            onPressed: onNext,
            child: Text(isLastRound ? 'Finish session' : 'Next pitch'),
          ),
        ],
      ),
    );
  }
}

class _StatChip extends StatelessWidget {
  const _StatChip({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        margin: const EdgeInsets.only(right: 8),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          color: Colors.white.withValues(alpha: 0.06),
        ),
        child: Column(
          children: [
            Text(
              label,
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: Colors.white54,
              ),
            ),
            const SizedBox(height: 2),
            Text(
              value,
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                fontWeight: FontWeight.w800,
              ),
            ),
          ],
        ),
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
