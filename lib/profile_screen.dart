import 'package:flutter/material.dart';

import 'app_state.dart';
import 'onboarding_gate.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _ageController = TextEditingController();

  String _gender = '응답 안 함';
  String _position = '타자';
  String _battingSide = '우타';
  String _experience = '입문';
  String _goal = '구종 인식';
  bool _saving = false;
  bool _initialized = false;
  String? _errorText;

  static const _genders = ['남성', '여성', '논바이너리', '응답 안 함'];
  static const _positions = ['타자', '투수', '포수', '내야수', '외야수', '코치'];
  static const _battingSides = ['좌타', '우타', '스위치', '모름'];
  static const _experiences = ['입문', '1~2년', '3~5년', '5년+'];
  static const _goals = ['구종 인식', '존 판정', '스윙 디시전', '실전 감각', '반응 속도'];

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_initialized) return;
    final store = BattersEyeScope.of(context);
    final profile = store.profile;
    _nameController.text = profile?.name ?? store.displayName;
    _ageController.text = (profile?.age ?? 0) <= 0
        ? ''
        : profile!.age.toString();
    _gender = profile?.gender.isNotEmpty == true ? profile!.gender : _gender;
    _position = profile?.position.isNotEmpty == true
        ? profile!.position
        : _position;
    _battingSide = profile?.battingSide.isNotEmpty == true
        ? profile!.battingSide
        : _battingSide;
    _experience = profile?.experience.isNotEmpty == true
        ? profile!.experience
        : _experience;
    _goal = profile?.goal.isNotEmpty == true ? profile!.goal : _goal;
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
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 28),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  '프로필 설정',
                  style: theme.textTheme.headlineLarge?.copyWith(
                    fontWeight: FontWeight.w800,
                    letterSpacing: -0.04,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  '나이, 성별, 포지션, 타석을 받으면 추천 레벨이 더 정확해진다.',
                  style: theme.textTheme.bodyLarge?.copyWith(
                    color: Colors.white.withValues(alpha: 0.72),
                    height: 1.45,
                  ),
                ),
                const SizedBox(height: 20),
                Container(
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(24),
                    gradient: const LinearGradient(
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                      colors: [
                        Color(0xFF10233C),
                        Color(0xFF162A4A),
                        Color(0xFF0D1B31),
                      ],
                    ),
                    border: Border.all(
                      color: Colors.white.withValues(alpha: 0.08),
                    ),
                  ),
                  child: Form(
                    key: _formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        TextFormField(
                          controller: _nameController,
                          decoration: const InputDecoration(
                            labelText: '이름 / 닉네임',
                            hintText: '예: 종현',
                          ),
                          validator: (value) {
                            if ((value ?? '').trim().isEmpty) {
                              return '이름을 입력해줘.';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 14),
                        TextFormField(
                          controller: _ageController,
                          keyboardType: TextInputType.number,
                          decoration: const InputDecoration(
                            labelText: '나이',
                            hintText: '예: 23',
                          ),
                          validator: (value) {
                            final text = (value ?? '').trim();
                            final parsed = int.tryParse(text);
                            if (parsed == null) return '숫자로 입력해줘.';
                            if (parsed <= 0) return '0보다 큰 숫자를 적어줘.';
                            if (parsed > 100) return '나이를 다시 확인해줘.';
                            return null;
                          },
                        ),
                        const SizedBox(height: 14),
                        _DropdownField(
                          label: '성별',
                          value: _gender,
                          items: _genders,
                          onChanged: (value) =>
                              setState(() => _gender = value ?? _gender),
                        ),
                        const SizedBox(height: 14),
                        _DropdownField(
                          label: '포지션',
                          value: _position,
                          items: _positions,
                          onChanged: (value) =>
                              setState(() => _position = value ?? _position),
                        ),
                        const SizedBox(height: 14),
                        Text(
                          '타석',
                          style: theme.textTheme.labelLarge?.copyWith(
                            color: Colors.white70,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Wrap(
                          spacing: 10,
                          runSpacing: 10,
                          children: _battingSides
                              .map(
                                (side) => ChoiceChip(
                                  label: Text(side),
                                  selected: _battingSide == side,
                                  onSelected: (_) =>
                                      setState(() => _battingSide = side),
                                ),
                              )
                              .toList(),
                        ),
                        const SizedBox(height: 14),
                        _DropdownField(
                          label: '경험치',
                          value: _experience,
                          items: _experiences,
                          onChanged: (value) => setState(
                            () => _experience = value ?? _experience,
                          ),
                        ),
                        const SizedBox(height: 14),
                        _DropdownField(
                          label: '오늘의 목표',
                          value: _goal,
                          items: _goals,
                          onChanged: (value) =>
                              setState(() => _goal = value ?? _goal),
                        ),
                        const SizedBox(height: 14),
                        Text(
                          '이 정보는 레벨 추천과 훈련 카드만 개인화하는 데 사용된다.',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: Colors.white.withValues(alpha: 0.58),
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
                            child: Text(_saving ? '저장 중…' : '프로필 저장하고 레벨 테스트로'),
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

class _DropdownField extends StatelessWidget {
  const _DropdownField({
    required this.label,
    required this.value,
    required this.items,
    required this.onChanged,
  });

  final String label;
  final String value;
  final List<String> items;
  final ValueChanged<String?> onChanged;

  @override
  Widget build(BuildContext context) {
    return DropdownButtonFormField<String>(
      initialValue: value,
      decoration: InputDecoration(labelText: label),
      items: items
          .map(
            (item) => DropdownMenuItem<String>(value: item, child: Text(item)),
          )
          .toList(),
      onChanged: onChanged,
    );
  }
}

class _ProfileHintCard extends StatelessWidget {
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
            '추천 기준',
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          Text(
            '프로필은 레벨 추천의 기준이 되고, 이후에는 훈련 리포트와 함께 누적된다.',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.72),
              height: 1.5,
            ),
          ),
        ],
      ),
    );
  }
}
