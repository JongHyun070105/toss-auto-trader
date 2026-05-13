import 'package:flutter/material.dart';

import 'app_copy.dart';
import 'app_state.dart';
import 'app_theme.dart';
import 'batters_eye_scope.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _ageController = TextEditingController();

  String _gender = 'male';
  String _position = 'batter';
  String _battingSide = 'right';
  String _experience = 'beginner';
  String _goal = 'pitch_recognition';
  bool _saving = false;
  bool _initialized = false;
  String? _errorText;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_initialized) return;
    final store = BattersEyeScope.of(context);
    final copy = context.copy;
    final profile = store.profile;
    _nameController.text = profile?.name ?? store.displayName;
    _ageController.text = (profile?.age ?? 0) <= 0 ? '' : profile!.age.toString();
    _gender = copy.normalizeProfileGender(profile?.gender ?? _gender);
    _position = copy.normalizeProfilePosition(profile?.position ?? _position);
    _battingSide = copy.normalizeProfileBattingSide(
      profile?.battingSide ?? _battingSide,
    );
    _experience = copy.normalizeProfileExperience(
      profile?.experience ?? _experience,
    );
    _goal = copy.normalizeProfileGoal(profile?.goal ?? _goal);
    _initialized = true;
  }

  @override
  void dispose() {
    _nameController.dispose();
    _ageController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;

    final store = BattersEyeScope.of(context);
    final age = int.tryParse(_ageController.text.trim()) ?? 0;
    final profile = UserProfile(
      name: _nameController.text.trim(),
      age: age,
      gender: _gender,
      position: _position,
      battingSide: _battingSide,
      experience: _experience,
      goal: _goal,
    );

    setState(() {
      _saving = true;
      _errorText = null;
    });

    final result = await store.saveProfile(profile);

    if (!mounted) return;

    setState(() {
      _saving = false;
      _errorText = result;
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final copy = context.copy;

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
                  copy.profileTitle,
                  style: theme.textTheme.headlineLarge?.copyWith(
                    fontWeight: FontWeight.w800,
                    letterSpacing: -0.04,
                    color: context.textPrimary,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  copy.profileIntro,
                  style: theme.textTheme.bodyLarge?.copyWith(
                    color: context.textSecondary,
                    height: 1.45,
                  ),
                ),
                const SizedBox(height: 20),
                Container(
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(24),
                    gradient: context.heroGradient,
                    border: Border.all(color: context.panelBorder),
                  ),
                  child: Form(
                    key: _formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        TextFormField(
                          controller: _nameController,
                          decoration: InputDecoration(
                            labelText: copy.profileNameLabel,
                            hintText: copy.profileNameHint,
                          ),
                          validator: (value) {
                            if ((value ?? '').trim().isEmpty) {
                              return copy.profileErrorName;
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 14),
                        TextFormField(
                          controller: _ageController,
                          keyboardType: TextInputType.number,
                          decoration: InputDecoration(
                            labelText: copy.profileAgeLabel,
                            hintText: copy.profileAgeHint,
                          ),
                          validator: (value) {
                            final text = (value ?? '').trim();
                            final parsed = int.tryParse(text);
                            if (text.isEmpty) return copy.profileErrorAgeRequired;
                            if (parsed == null) return copy.profileErrorAge;
                            if (parsed <= 0) return copy.profileErrorAgePositive;
                            if (parsed > 100) return copy.profileErrorAgeRange;
                            return null;
                          },
                        ),
                        const SizedBox(height: 14),
                        _ChoiceDropdown(
                          label: copy.profileGenderLabel,
                          value: _gender,
                          choices: copy.genderChoices,
                          onChanged: (value) =>
                              setState(() => _gender = value ?? _gender),
                        ),
                        const SizedBox(height: 14),
                        _ChoiceDropdown(
                          label: copy.profilePositionLabel,
                          value: _position,
                          choices: copy.positionChoices,
                          onChanged: (value) =>
                              setState(() => _position = value ?? _position),
                        ),
                        const SizedBox(height: 14),
                        Text(
                          copy.profileBattingSideLabel,
                          style: theme.textTheme.labelLarge?.copyWith(
                            color: context.textSecondary,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Wrap(
                          spacing: 10,
                          runSpacing: 10,
                          children: copy.battingSideChoices
                              .map(
                                (side) => ChoiceChip(
                                  label: Text(side.label(copy.language)),
                                  selected: _battingSide == side.code,
                                  onSelected: (_) =>
                                      setState(() => _battingSide = side.code),
                                ),
                              )
                              .toList(),
                        ),
                        const SizedBox(height: 14),
                        _ChoiceDropdown(
                          label: copy.profileExperienceLabel,
                          value: _experience,
                          choices: copy.experienceChoices,
                          onChanged: (value) => setState(
                            () => _experience = value ?? _experience,
                          ),
                        ),
                        const SizedBox(height: 14),
                        _ChoiceDropdown(
                          label: copy.profileGoalLabel,
                          value: _goal,
                          choices: copy.goalChoices,
                          onChanged: (value) =>
                              setState(() => _goal = value ?? _goal),
                        ),
                        const SizedBox(height: 14),
                        Text(
                          copy.profileNote,
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: context.textMuted,
                          ),
                        ),
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
                        const SizedBox(height: 18),
                        SizedBox(
                          width: double.infinity,
                          child: FilledButton(
                            onPressed: _saving ? null : _save,
                            child: Text(
                              _saving ? copy.profileSaving : copy.profileSaveCta,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                _ProfileHintCard(),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ChoiceDropdown extends StatelessWidget {
  const _ChoiceDropdown({
    required this.label,
    required this.value,
    required this.choices,
    required this.onChanged,
  });

  final String label;
  final String value;
  final List<ProfileChoice> choices;
  final ValueChanged<String?> onChanged;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final currentValue = choices.any((choice) => choice.code == value)
        ? value
        : choices.first.code;

    return DropdownButtonFormField<String>(
      initialValue: currentValue,
      items: choices
          .map(
            (choice) => DropdownMenuItem<String>(
              value: choice.code,
              child: Text(choice.label(copy.language)),
            ),
          )
          .toList(),
      decoration: InputDecoration(labelText: label),
      onChanged: onChanged,
    );
  }
}

class _ProfileHintCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final copy = context.copy;

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        color: context.panelFill,
        border: Border.all(color: context.panelBorder),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.tune_rounded, color: theme.colorScheme.primary),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  copy.profileRecommendationTitle,
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w800,
                    color: context.textPrimary,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  copy.profileRecommendationBody,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: context.textSecondary,
                    height: 1.45,
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
