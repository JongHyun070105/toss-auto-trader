import 'package:flutter/material.dart';

import 'onboarding_gate.dart';

class AuthScreen extends StatefulWidget {
  const AuthScreen({super.key});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();

  bool _isSignUp = true;
  bool _obscurePassword = true;
  bool _submitting = false;
  String? _errorText;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;

    final store = BattersEyeScope.of(context);
    final email = _emailController.text;
    final password = _passwordController.text;

    setState(() {
      _submitting = true;
      _errorText = null;
    });

    final result = _isSignUp
        ? await store.signUp(email, password)
        : await store.login(email, password);

    if (!mounted) return;

    setState(() {
      _submitting = false;
      _errorText = result;
    });

    if (result == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            _isSignUp ? '가입 완료. 프로필을 이어서 입력해줘.' : '환영해. 프로필을 이어서 확인하자.',
          ),
        ),
      );
    }
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
                  'Batter’s Eye',
                  style: theme.textTheme.headlineLarge?.copyWith(
                    fontWeight: FontWeight.w800,
                    letterSpacing: -0.04,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  '계정부터 만들고, 프로필과 레벨을 쌓아가는 개인 훈련 루프.',
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
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      ToggleButtons(
                        isSelected: [_isSignUp, !_isSignUp],
                        onPressed: (index) {
                          setState(() {
                            _isSignUp = index == 0;
                            _errorText = null;
                          });
                        },
                        borderRadius: BorderRadius.circular(18),
                        selectedColor: Colors.black,
                        fillColor: theme.colorScheme.primary,
                        color: Colors.white70,
                        constraints: const BoxConstraints(
                          minHeight: 44,
                          minWidth: 104,
                        ),
                        children: const [
                          Padding(
                            padding: EdgeInsets.symmetric(horizontal: 8),
                            child: Text('회원가입'),
                          ),
                          Padding(
                            padding: EdgeInsets.symmetric(horizontal: 8),
                            child: Text('로그인'),
                          ),
                        ],
                      ),
                      const SizedBox(height: 18),
                      Form(
                        key: _formKey,
                        child: Column(
                          children: [
                            TextFormField(
                              controller: _emailController,
                              keyboardType: TextInputType.emailAddress,
                              textInputAction: TextInputAction.next,
                              autofillHints: const [AutofillHints.email],
                              decoration: const InputDecoration(
                                labelText: '이메일',
                                hintText: 'you@example.com',
                              ),
                              validator: (value) {
                                final text = (value ?? '').trim();
                                if (text.isEmpty) return '이메일을 입력해줘.';
                                if (!text.contains('@') ||
                                    !text.contains('.')) {
                                  return '이메일 형식이 아니야.';
                                }
                                return null;
                              },
                            ),
                            const SizedBox(height: 14),
                            TextFormField(
                              controller: _passwordController,
                              obscureText: _obscurePassword,
                              textInputAction: TextInputAction.done,
                              autofillHints: const [AutofillHints.password],
                              onFieldSubmitted: (_) => _submit(),
                              decoration: InputDecoration(
                                labelText: '비밀번호',
                                hintText: _isSignUp ? '6자 이상' : '기존 비밀번호',
                                suffixIcon: IconButton(
                                  onPressed: () {
                                    setState(() {
                                      _obscurePassword = !_obscurePassword;
                                    });
                                  },
                                  icon: Icon(
                                    _obscurePassword
                                        ? Icons.visibility_rounded
                                        : Icons.visibility_off_rounded,
                                  ),
                                ),
                              ),
                              validator: (value) {
                                final text = (value ?? '').trim();
                                if (text.length < 6) return '비밀번호는 6자 이상이어야 해.';
                                return null;
                              },
                            ),
                            const SizedBox(height: 12),
                            Align(
                              alignment: Alignment.centerLeft,
                              child: Text(
                                _isSignUp
                                    ? '가입 후 프로필에서 나이·성별·포지션을 받는다.'
                                    : '이 기기에 저장된 계정으로 바로 이어진다.',
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: Colors.white.withValues(alpha: 0.58),
                                ),
                              ),
                            ),
                            if (_errorText != null) ...[
                              const SizedBox(height: 12),
                              Align(
                                alignment: Alignment.centerLeft,
                                child: Text(
                                  _errorText!,
                                  style: theme.textTheme.bodyMedium?.copyWith(
                                    color: theme.colorScheme.error,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ),
                            ],
                            const SizedBox(height: 18),
                            SizedBox(
                              width: double.infinity,
                              child: FilledButton(
                                onPressed: _submitting ? null : _submit,
                                child: Text(
                                  _isSignUp ? '회원가입하고 시작' : '로그인하고 이어가기',
                                ),
                              ),
                            ),
                            const SizedBox(height: 10),
                            TextButton(
                              onPressed: _submitting
                                  ? null
                                  : () {
                                      setState(() {
                                        _isSignUp = !_isSignUp;
                                        _errorText = null;
                                      });
                                    },
                              child: Text(
                                _isSignUp ? '이미 계정이 있어? 로그인' : '새 계정 만들기',
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                _AuthHintCard(),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _AuthHintCard extends StatelessWidget {
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
            '왜 계정이 먼저인가',
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          Text(
            '프로필과 레벨 테스트가 쌓여야 오늘의 훈련이 단순 반복이 아니라 개인화된 코치 루프로 바뀐다.',
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
