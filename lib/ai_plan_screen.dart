import 'package:flutter/material.dart';

import 'ai_coach.dart';
import 'app_copy.dart';
import 'app_state.dart';
import 'app_theme.dart';
import 'batters_eye_scope.dart';

class AiPlanScreen extends StatefulWidget {
  const AiPlanScreen({super.key});

  @override
  State<AiPlanScreen> createState() => _AiPlanScreenState();
}

class _AiPlanScreenState extends State<AiPlanScreen> {
  bool _loading = true;
  bool _saving = false;
  AiTrainingPlan? _plan;
  String? _errorText;
  bool _initialized = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_initialized) return;
    _initialized = true;
    _generatePlan();
  }

  Future<void> _generatePlan() async {
    final copy = context.copy;
    final store = BattersEyeScope.of(context);
    final profile = store.profile;
    final placement = store.placementResult;
    if (profile == null || placement == null) {
      setState(() {
        _loading = false;
        _errorText = copy.aiPlanMissingData;
      });
      return;
    }

    setState(() {
      _loading = true;
      _errorText = null;
    });

    final plan = await const AiCoachPlanner().buildPlan(
      language: store.language,
      profile: profile,
      placement: placement,
      lastReport: store.lastTrainingReport,
    );

    if (!mounted) return;
    setState(() {
      _plan = plan;
      _loading = false;
    });
  }

  Future<void> _saveAndContinue() async {
    final plan = _plan;
    if (plan == null || _saving) return;
    setState(() => _saving = true);
    await BattersEyeScope.of(context).saveAiPlan(plan);
    if (!mounted) return;
    setState(() => _saving = false);
  }

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final theme = Theme.of(context);
    final plan = _plan;

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
                  copy.aiPlanTitle,
                  style: theme.textTheme.headlineLarge?.copyWith(
                    fontWeight: FontWeight.w900,
                    letterSpacing: -0.04,
                    color: context.textPrimary,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  copy.aiPlanSubtitle,
                  style: theme.textTheme.bodyLarge?.copyWith(
                    color: context.textSecondary,
                    height: 1.45,
                  ),
                ),
                const SizedBox(height: 20),
                if (_loading) ...[
                  Container(
                    padding: const EdgeInsets.all(22),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(28),
                      gradient: context.heroGradient,
                      border: Border.all(color: context.panelBorder),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _TagRow(
                          label: copy.aiPlanModelLabel,
                          value: kGeminiModel,
                        ),
                        const SizedBox(height: 16),
                        const LinearProgressIndicator(minHeight: 6),
                        const SizedBox(height: 16),
                        Text(
                          copy.aiPlanLoadingBody,
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: Colors.white.withValues(alpha: 0.76),
                            height: 1.45,
                          ),
                        ),
                      ],
                    ),
                  ),
                ] else if (plan != null) ...[
                  Container(
                    padding: const EdgeInsets.all(22),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(28),
                      gradient: context.heroGradient,
                      border: Border.all(color: context.panelBorder),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _TagRow(
                          label: copy.aiPlanModelLabel,
                          value: plan.model,
                        ),
                        const SizedBox(height: 14),
                        Text(
                          plan.headline,
                          style: theme.textTheme.headlineSmall?.copyWith(
                            fontWeight: FontWeight.w900,
                            letterSpacing: -0.03,
                            color: Colors.white,
                          ),
                        ),
                        const SizedBox(height: 10),
                        Text(
                          plan.focusSummary,
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: Colors.white.withValues(alpha: 0.76),
                            height: 1.45,
                          ),
                        ),
                        const SizedBox(height: 14),
                        Text(
                          plan.usedLiveModel
                              ? copy.aiPlanLiveNote
                              : copy.aiPlanFallbackNote,
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: Colors.white.withValues(alpha: 0.64),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 14),
                  _InsightCard(
                    title: copy.aiPlanStrengthLabel,
                    body: plan.strength,
                    accent: theme.colorScheme.secondary,
                  ),
                  const SizedBox(height: 12),
                  _InsightCard(
                    title: copy.aiPlanRiskLabel,
                    body: plan.risk,
                    accent: theme.colorScheme.tertiary,
                  ),
                  const SizedBox(height: 12),
                  _InsightCard(
                    title: copy.aiPlanWhyNowLabel,
                    body: plan.whyNow,
                    accent: theme.colorScheme.primary,
                  ),
                  const SizedBox(height: 18),
                  Text(
                    copy.aiPlanWeekLabel,
                    style: theme.textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                  const SizedBox(height: 12),
                  ...plan.sevenDayPlan.map(
                    (item) => Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: _PlanDayCard(body: item),
                    ),
                  ),
                  const SizedBox(height: 8),
                  FilledButton(
                    onPressed: _saving ? null : _saveAndContinue,
                    child: Text(copy.aiPlanPrimaryCta),
                  ),
                ] else ...[
                  Container(
                    padding: const EdgeInsets.all(18),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(24),
                      color: context.panelFill,
                      border: Border.all(color: context.panelBorder),
                    ),
                    child: Text(
                      _errorText ?? copy.aiPlanLoadingBody,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: context.textSecondary,
                        height: 1.45,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _TagRow extends StatelessWidget {
  const _TagRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.08),
            borderRadius: BorderRadius.circular(999),
          ),
          child: Text(
            label,
            style: Theme.of(context).textTheme.labelLarge?.copyWith(
              color: Colors.white.withValues(alpha: 0.72),
            ),
          ),
        ),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.12),
            borderRadius: BorderRadius.circular(999),
          ),
          child: Text(
            value,
            style: Theme.of(context).textTheme.labelLarge?.copyWith(
              color: Colors.white,
              fontWeight: FontWeight.w800,
            ),
          ),
        ),
      ],
    );
  }
}

class _InsightCard extends StatelessWidget {
  const _InsightCard({
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
        color: context.panelFill,
        border: Border.all(color: accent.withValues(alpha: 0.22)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w900,
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

class _PlanDayCard extends StatelessWidget {
  const _PlanDayCard({required this.body});

  final String body;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        color: context.panelSoftFill,
        border: Border.all(color: context.panelBorder),
      ),
      child: Text(
        body,
        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: context.textPrimary,
              height: 1.45,
            ),
      ),
    );
  }
}
