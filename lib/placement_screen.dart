import 'dart:async';

import 'package:flutter/material.dart';

import 'app_copy.dart';
import 'app_theme.dart';
import 'batters_eye_scope.dart';
import 'placement.dart';
import 'session.dart';

class PlacementScreen extends StatefulWidget {
  const PlacementScreen({super.key});

  @override
  State<PlacementScreen> createState() => _PlacementScreenState();
}

class _PlacementScreenState extends State<PlacementScreen> {
  int _index = 0;
  final List<int> _answers = List<int>.filled(
    PlacementEngine.questions.length,
    -1,
  );
  Timer? _revealTimer;
  bool _showPrompt = false;
  bool _revealed = false;
  int? _selectedChoice;
  PlacementResult? _result;
  String? _errorText;
  bool _saving = false;

  PlacementQuestion get _question => PlacementEngine.questions[_index];
  double get _progress {
    if (_result != null) return 1;
    if (!_showPrompt) {
      return _index / PlacementEngine.questions.length;
    }
    return (_index + 1) / PlacementEngine.questions.length;
  }

  void _startPitch() {
    if (_showPrompt || _revealed) return;

    _revealTimer?.cancel();
    setState(() {
      _errorText = null;
    });

    _revealTimer = Timer(const Duration(milliseconds: 650), () {
      if (!mounted) return;
      setState(() {
        _showPrompt = true;
      });
    });
  }

  void _selectChoice(int choiceIndex) {
    if (!_showPrompt || _revealed) return;
    setState(() {
      _selectedChoice = choiceIndex;
      _answers[_index] = choiceIndex;
      _revealed = true;
      _errorText = null;
    });
  }

  void _next() {
    if (!_revealed) return;

    if (_index == PlacementEngine.questions.length - 1) {
      setState(() {
        _result = PlacementEngine.evaluate(_answers);
      });
      return;
    }

    setState(() {
      _index += 1;
      _selectedChoice = null;
      _revealed = false;
      _showPrompt = false;
      _errorText = null;
    });
  }

  @override
  void dispose() {
    _revealTimer?.cancel();
    super.dispose();
  }

  Future<void> _saveResult() async {
    final result = _result;
    if (result == null) return;

    final store = BattersEyeScope.of(context);
    setState(() {
      _saving = true;
      _errorText = null;
    });

    await store.savePlacement(result);

    if (!mounted) return;
    setState(() {
      _saving = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final theme = Theme.of(context);
    final result = _result;

    return Scaffold(
      body: Container(
        decoration: BoxDecoration(gradient: context.pageGradient),
        child: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 28),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  copy.placementTitle,
                  style: theme.textTheme.headlineLarge?.copyWith(
                    fontWeight: FontWeight.w800,
                    letterSpacing: -0.04,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  copy.placementIntro,
                  style: theme.textTheme.bodyLarge?.copyWith(
                    color: context.textSecondary,
                    height: 1.45,
                  ),
                ),
                const SizedBox(height: 20),
                Container(
                  padding: const EdgeInsets.all(18),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(24),
                    color: context.panelFill,
                    border: Border.all(color: context.panelBorder),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            copy.placementStageLabel(
                              showPrompt: _showPrompt,
                              hasResult: result != null,
                              index: _index,
                              total: PlacementEngine.questions.length,
                            ),
                            style: theme.textTheme.titleMedium?.copyWith(
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                          Text(
                            '${(_progress * 100).round()}%',
                            style: theme.textTheme.labelLarge?.copyWith(
                              color: theme.colorScheme.primary,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      LinearProgressIndicator(
                        value: result == null ? _progress : 1,
                        backgroundColor: context.panelSoftFill,
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                if (result == null) ...[
                  AnimatedSwitcher(
                    duration: const Duration(milliseconds: 220),
                    child: _showPrompt
                        ? KeyedSubtree(
                            key: const ValueKey('question'),
                            child: _QuestionCard(
                              question: _question,
                              selectedChoice: _selectedChoice,
                              revealed: _revealed,
                              onChoiceSelected: _selectChoice,
                              onNext: _next,
                            ),
                          )
                        : KeyedSubtree(
                            key: const ValueKey('warmup'),
                            child: _WarmupCard(
                              question: _question,
                              onStart: _startPitch,
                            ),
                          ),
                  ),
                ] else ...[
                  _ResultCard(
                    result: result,
                    onSave: _saveResult,
                    saving: _saving,
                  ),
                ],
                if (_errorText != null) ...[
                  const SizedBox(height: 12),
                  Text(
                    _errorText!,
                    style: theme.textTheme.bodyMedium?.copyWith(
                      color: theme.colorScheme.error,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
                const SizedBox(height: 16),
                _PlacementHintCard(),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _WarmupCard extends StatelessWidget {
  const _WarmupCard({required this.question, required this.onStart});

  final PlacementQuestion question;
  final VoidCallback onStart;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final theme = Theme.of(context);
    final accent = _accentForMode(question.mode, theme.colorScheme);

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
          Row(
            children: [
              _StatPill(
                label: copy.placementPrepLabel,
                value: copy.trainingModeLabel(question.mode),
              ),
              const SizedBox(width: 8),
              _StatPill(
                label: copy.placementFocusLabel,
                value: copy.trainingModeFocus(question.mode),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            copy.placementQuestionTitle(question),
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w900,
              letterSpacing: -0.03,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            copy.trainingModeHero(question.mode),
            style: theme.textTheme.bodyMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.74),
              height: 1.45,
            ),
          ),
          const SizedBox(height: 16),
          _PlacementZoneBoard(mode: question.mode, accent: accent),
          const SizedBox(height: 16),
          Text(
            copy.placementQuickHint,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.72),
              height: 1.45,
            ),
          ),
          const SizedBox(height: 18),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: onStart,
              icon: const Icon(Icons.play_arrow_rounded),
              label: Text(copy.placementStartPitch),
            ),
          ),
        ],
      ),
    );
  }
}

class _PlacementZoneBoard extends StatelessWidget {
  const _PlacementZoneBoard({required this.mode, required this.accent});

  final TrainingMode mode;
  final Color accent;

  int get _highlightIndex => switch (mode) {
    TrainingMode.pitchType => 1,
    TrainingMode.strikeZone => 4,
    TrainingMode.swingDecision => 7,
  };

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final theme = Theme.of(context);
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
                                    child: TweenAnimationBuilder<double>(
                                      tween: Tween(begin: 0.88, end: 1.0),
                                      duration: const Duration(
                                        milliseconds: 900,
                                      ),
                                      curve: Curves.easeInOut,
                                      builder: (context, value, child) {
                                        return Transform.scale(
                                          scale: value,
                                          child: child,
                                        );
                                      },
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
                    copy.placementZoneBoardLabel,
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
                    copy.placementReleaseLaneLabel,
                    style: theme.textTheme.labelLarge?.copyWith(
                      color: Colors.white.withValues(alpha: 0.78),
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Container(
                    width: 74,
                    height: 6,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(999),
                      gradient: LinearGradient(
                        colors: [accent.withValues(alpha: 0.15), accent],
                      ),
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

Color _accentForMode(TrainingMode mode, ColorScheme scheme) => switch (mode) {
  TrainingMode.pitchType => scheme.primary,
  TrainingMode.strikeZone => scheme.secondary,
  TrainingMode.swingDecision => scheme.tertiary,
};

class _StatPill extends StatelessWidget {
  const _StatPill({required this.label, required this.value});

  final String label;
  final String value;

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

class _QuestionCard extends StatelessWidget {
  const _QuestionCard({
    required this.question,
    required this.selectedChoice,
    required this.revealed,
    required this.onChoiceSelected,
    required this.onNext,
  });

  final PlacementQuestion question;
  final int? selectedChoice;
  final bool revealed;
  final ValueChanged<int> onChoiceSelected;
  final VoidCallback onNext;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
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
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            copy.placementQuestionTitle(question),
            style: theme.textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 10),
          Text(
            copy.placementQuestionPrompt(question),
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 18),
          ...List.generate(question.choices.length, (index) {
            final choice = question.choices[index];
            final isSelected = selectedChoice == index;
            final isCorrect = revealed && index == question.correctIndex;
            final isWrong =
                revealed && isSelected && index != question.correctIndex;
            final borderColor = isCorrect
                ? Theme.of(context).colorScheme.secondary
                : isWrong
                ? Theme.of(context).colorScheme.error
                : Colors.white.withValues(alpha: 0.10);

            return Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: InkWell(
                borderRadius: BorderRadius.circular(18),
                onTap: revealed ? null : () => onChoiceSelected(index),
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 16,
                  ),
                  decoration: BoxDecoration(
                    color: isSelected
                        ? Colors.white.withValues(alpha: 0.10)
                        : Colors.white.withValues(alpha: 0.04),
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(color: borderColor),
                  ),
                  child: Row(
                    children: [
                      CircleAvatar(
                        radius: 14,
                        backgroundColor: isCorrect
                            ? Theme.of(context).colorScheme.secondary
                            : isSelected
                            ? Theme.of(context).colorScheme.primary
                            : Colors.white.withValues(alpha: 0.10),
                        child: Text(
                          String.fromCharCode(65 + index),
                          style: TextStyle(
                            color: isCorrect || isSelected
                                ? Colors.black
                                : Colors.white,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          copy.trainingChoiceLabel(choice),
                          style: theme.textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                      if (isCorrect)
                        const Icon(
                          Icons.check_circle_rounded,
                          color: Colors.greenAccent,
                        )
                      else if (isWrong)
                        Icon(
                          Icons.close_rounded,
                          color: theme.colorScheme.error,
                        ),
                    ],
                  ),
                ),
              ),
            );
          }),
          if (revealed) ...[
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.05),
                borderRadius: BorderRadius.circular(18),
                border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    copy.placementCorrectFeedback(
                      selectedChoice == question.correctIndex,
                      question.correctChoice,
                    ),
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    copy.placementQuestionCoachNote(question),
                    style: theme.textTheme.bodyMedium?.copyWith(
                      color: Colors.white.withValues(alpha: 0.72),
                      height: 1.45,
                    ),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: 18),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: revealed ? onNext : null,
              child: Text(_buttonLabel(context)),
            ),
          ),
        ],
      ),
    );
  }

  String _buttonLabel(BuildContext context) {
    final copy = AppCopy(BattersEyeScope.of(context).language);
    if (!revealed) return copy.placementSelectFirst;
    if (question.id == PlacementEngine.questions.last.id) {
      return copy.placementViewResult;
    }
    return copy.placementNextQuestion;
  }
}

class _ResultCard extends StatelessWidget {
  const _ResultCard({
    required this.result,
    required this.onSave,
    required this.saving,
  });

  final PlacementResult result;
  final VoidCallback onSave;
  final bool saving;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
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
          Text(
            copy.placementRecommendedResultTitle,
            style: theme.textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 10),
          Text(
            copy.placementLevelLabel(result.level),
            style: theme.textTheme.headlineMedium?.copyWith(
              fontWeight: FontWeight.w900,
              letterSpacing: -0.03,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '${result.score}% · ${result.correctCount}/${result.totalQuestions} ${copy.reportAccuracyLabel}',
            style: theme.textTheme.titleMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.72),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            copy.placementRecommendation(result),
            style: theme.textTheme.bodyMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.72),
              height: 1.45,
            ),
          ),
          const SizedBox(height: 18),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              _ResultPill(
                label: copy.placementIntensityLabel,
                value: copy.placementIntensity(result.level),
              ),
              _ResultPill(
                label: copy.placementRecommendedModeLabel,
                value: copy.trainingModeLabel(result.recommendedMode),
              ),
            ],
          ),
          const SizedBox(height: 18),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: saving ? null : onSave,
              child: Text(
                saving ? copy.profileSaving : copy.placementSaveAndGoHome,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ResultPill extends StatelessWidget {
  const _ResultPill({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
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
              color: Colors.white.withValues(alpha: 0.55),
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

class _PlacementHintCard extends StatelessWidget {
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
          Text(
            copy.placementFlowTitle,
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          Text(
            copy.placementFlowBody,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: context.textSecondary,
              height: 1.5,
            ),
          ),
        ],
      ),
    );
  }
}
