import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'placement.dart';
import 'session.dart';

const _storageKey = 'batters_eye.local_state.v1';

enum OnboardingStage { auth, profile, placement, dashboard }

class UserProfile {
  const UserProfile({
    required this.name,
    required this.age,
    required this.gender,
    required this.position,
    required this.battingSide,
    required this.experience,
    required this.goal,
  });

  final String name;
  final int age;
  final String gender;
  final String position;
  final String battingSide;
  final String experience;
  final String goal;

  List<String> get chips => [
    if (age > 0) '$age세',
    gender,
    position,
    battingSide,
    experience,
    goal,
  ];

  Map<String, dynamic> toJson() => {
    'name': name,
    'age': age,
    'gender': gender,
    'position': position,
    'battingSide': battingSide,
    'experience': experience,
    'goal': goal,
  };

  factory UserProfile.fromJson(Map<String, dynamic> json) {
    return UserProfile(
      name: (json['name'] as String?) ?? '',
      age: (json['age'] as num?)?.toInt() ?? 0,
      gender: (json['gender'] as String?) ?? '',
      position: (json['position'] as String?) ?? '',
      battingSide: (json['battingSide'] as String?) ?? '',
      experience: (json['experience'] as String?) ?? '',
      goal: (json['goal'] as String?) ?? '',
    );
  }
}

class TrainingReport {
  const TrainingReport({
    required this.mode,
    required this.correctCount,
    required this.totalRounds,
    required this.averageReactionTime,
    required this.primaryWeakSpot,
    required this.completedAt,
  });

  final TrainingMode mode;
  final int correctCount;
  final int totalRounds;
  final Duration averageReactionTime;
  final String primaryWeakSpot;
  final DateTime completedAt;

  double get accuracy => totalRounds == 0 ? 0 : correctCount / totalRounds;
  int get accuracyPercent => (accuracy * 100).round();

  String get coachLine {
    if (totalRounds == 0) return '아직 기록이 없어. 첫 세션을 짧게 끝내자.';
    if (accuracy >= 0.8) return '좋아. 같은 기준으로 난도를 한 단계 올려보자.';
    return '다음 세션은 $primaryWeakSpot 하나만 잡고 가자.';
  }

  Map<String, dynamic> toJson() => {
    'mode': mode.name,
    'correctCount': correctCount,
    'totalRounds': totalRounds,
    'averageReactionMs': averageReactionTime.inMilliseconds,
    'primaryWeakSpot': primaryWeakSpot,
    'completedAt': completedAt.toIso8601String(),
  };

  factory TrainingReport.fromSummary(TrainingSummary summary) {
    return TrainingReport(
      mode: summary.mode,
      correctCount: summary.correctCount,
      totalRounds: summary.totalRounds,
      averageReactionTime: summary.averageReactionTime,
      primaryWeakSpot: summary.primaryWeakSpot,
      completedAt: DateTime.now(),
    );
  }

  factory TrainingReport.fromJson(Map<String, dynamic> json) {
    return TrainingReport(
      mode: _trainingModeFromName(json['mode'] as String?),
      correctCount: _readInt(json['correctCount'], fallback: 0),
      totalRounds: _readInt(json['totalRounds'], fallback: 0),
      averageReactionTime: Duration(
        milliseconds: _readInt(json['averageReactionMs'], fallback: 0),
      ),
      primaryWeakSpot: (json['primaryWeakSpot'] as String?) ?? '기본 읽기',
      completedAt:
          DateTime.tryParse((json['completedAt'] as String?) ?? '') ??
          DateTime.fromMillisecondsSinceEpoch(0),
    );
  }
}

class LocalAccount {
  const LocalAccount({
    required this.email,
    required this.passwordHash,
    this.profile,
    this.placementResult,
    this.lastTrainingReport,
    this.completedSessionCount = 0,
  });

  final String email;
  final String passwordHash;
  final UserProfile? profile;
  final PlacementResult? placementResult;
  final TrainingReport? lastTrainingReport;
  final int completedSessionCount;

  LocalAccount copyWith({
    UserProfile? profile,
    PlacementResult? placementResult,
    TrainingReport? lastTrainingReport,
    int? completedSessionCount,
  }) {
    return LocalAccount(
      email: email,
      passwordHash: passwordHash,
      profile: profile ?? this.profile,
      placementResult: placementResult ?? this.placementResult,
      lastTrainingReport: lastTrainingReport ?? this.lastTrainingReport,
      completedSessionCount:
          completedSessionCount ?? this.completedSessionCount,
    );
  }

  Map<String, dynamic> toJson() => {
    'email': email,
    'passwordHash': passwordHash,
    'profile': profile?.toJson(),
    'placementResult': placementResult?.toJson(),
    'lastTrainingReport': lastTrainingReport?.toJson(),
    'completedSessionCount': completedSessionCount,
  };

  factory LocalAccount.fromJson(Map<String, dynamic> json) {
    final profileJson = json['profile'];
    final placementJson = json['placementResult'];
    final reportJson = json['lastTrainingReport'];

    return LocalAccount(
      email: _normalizeEmail((json['email'] as String?) ?? ''),
      passwordHash: (json['passwordHash'] as String?) ?? '',
      profile: profileJson is Map<String, dynamic>
          ? UserProfile.fromJson(profileJson)
          : null,
      placementResult: placementJson is Map<String, dynamic>
          ? PlacementResult.fromJson(placementJson)
          : null,
      lastTrainingReport: reportJson is Map<String, dynamic>
          ? TrainingReport.fromJson(reportJson)
          : null,
      completedSessionCount:
          (json['completedSessionCount'] as num?)?.toInt() ?? 0,
    );
  }
}

class BattersEyeStore extends ChangeNotifier {
  BattersEyeStore._({
    SharedPreferences? preferences,
    Map<String, LocalAccount>? accounts,
    String? currentEmail,
    bool isLoaded = false,
  }) : _preferences = preferences,
       _accounts = accounts ?? <String, LocalAccount>{},
       _currentEmail = currentEmail,
       _isLoaded = isLoaded;

  factory BattersEyeStore.memory({
    Map<String, LocalAccount>? accounts,
    String? currentEmail,
  }) {
    return BattersEyeStore._(
      accounts: accounts,
      currentEmail: currentEmail == null ? null : _normalizeEmail(currentEmail),
      isLoaded: true,
    );
  }

  static Future<BattersEyeStore> create() async {
    final preferences = await SharedPreferences.getInstance();
    final store = BattersEyeStore._(preferences: preferences);
    await store.load();
    return store;
  }

  final SharedPreferences? _preferences;
  Map<String, LocalAccount> _accounts;
  String? _currentEmail;
  bool _isLoaded;

  bool get isLoaded => _isLoaded;
  String? get currentEmail => _currentEmail;
  Map<String, LocalAccount> get accounts => Map.unmodifiable(_accounts);

  LocalAccount? get currentAccount {
    final email = _currentEmail;
    if (email == null) return null;
    return _accounts[email];
  }

  String get displayName {
    final account = currentAccount;
    final profileName = account?.profile?.name.trim();
    if (profileName != null && profileName.isNotEmpty) return profileName;
    final email = _currentEmail;
    if (email == null) return '코치';
    return email.split('@').first;
  }

  UserProfile? get profile => currentAccount?.profile;
  PlacementResult? get placementResult => currentAccount?.placementResult;
  TrainingReport? get lastTrainingReport => currentAccount?.lastTrainingReport;
  int get completedSessionCount => currentAccount?.completedSessionCount ?? 0;
  PlacementLevel get placementLevel =>
      placementResult?.level ?? PlacementLevel.rookie;
  TrainingMode get recommendedMode =>
      placementResult?.recommendedMode ?? TrainingMode.pitchType;

  OnboardingStage get stage {
    final account = currentAccount;
    if (account == null) return OnboardingStage.auth;
    if (account.profile == null) return OnboardingStage.profile;
    if (account.placementResult == null) return OnboardingStage.placement;
    return OnboardingStage.dashboard;
  }

  Future<void> load() async {
    if (_isLoaded) return;
    final raw = _preferences?.getString(_storageKey);
    if (raw != null && raw.isNotEmpty) {
      _restoreFromJson(raw);
    }
    _isLoaded = true;
    notifyListeners();
  }

  Future<String?> signUp(String email, String password) async {
    final normalizedEmail = _normalizeEmail(email);
    final validationError = _validateCredentials(normalizedEmail, password);
    if (validationError != null) return validationError;
    if (_accounts.containsKey(normalizedEmail)) {
      return '이미 등록된 이메일이야. 로그인으로 들어와줘.';
    }

    _accounts[normalizedEmail] = LocalAccount(
      email: normalizedEmail,
      passwordHash: hashPassword(normalizedEmail, password),
    );
    _currentEmail = normalizedEmail;
    await _persistAndNotify();
    return null;
  }

  Future<String?> login(String email, String password) async {
    final normalizedEmail = _normalizeEmail(email);
    final account = _accounts[normalizedEmail];
    if (account == null) return '아직 가입되지 않은 이메일이야.';
    if (account.passwordHash != hashPassword(normalizedEmail, password)) {
      return '비밀번호가 맞지 않아. 천천히 다시 확인해줘.';
    }

    _currentEmail = normalizedEmail;
    await _persistAndNotify();
    return null;
  }

  Future<void> logout() async {
    _currentEmail = null;
    await _persistAndNotify();
  }

  Future<String?> saveProfile(UserProfile profile) async {
    final account = currentAccount;
    if (account == null) return '먼저 로그인해줘.';
    if (profile.name.trim().isEmpty) return '이름을 한 글자 이상 적어줘.';
    if (profile.age < 0) return '나이는 0 이상의 숫자로 적어줘.';

    _accounts[account.email] = account.copyWith(profile: profile);
    await _persistAndNotify();
    return null;
  }

  Future<void> savePlacement(PlacementResult result) async {
    final account = currentAccount;
    if (account == null) return;

    _accounts[account.email] = account.copyWith(placementResult: result);
    await _persistAndNotify();
  }

  Future<void> recordTrainingSummary(TrainingSummary summary) async {
    final account = currentAccount;
    if (account == null) return;

    _accounts[account.email] = account.copyWith(
      lastTrainingReport: TrainingReport.fromSummary(summary),
      completedSessionCount: account.completedSessionCount + 1,
    );
    await _persistAndNotify();
  }

  String exportJson() {
    return jsonEncode({
      'currentEmail': _currentEmail,
      'accounts': _accounts.map((key, value) => MapEntry(key, value.toJson())),
    });
  }

  void restoreForTest(String raw) {
    _restoreFromJson(raw);
    _isLoaded = true;
    notifyListeners();
  }

  static String hashPassword(String normalizedEmail, String password) {
    final payload = utf8.encode(
      '${_normalizeEmail(normalizedEmail)}:$password',
    );
    return sha256.convert(payload).toString();
  }

  Future<void> _persistAndNotify() async {
    if (_preferences != null) {
      await _preferences.setString(_storageKey, exportJson());
    }
    notifyListeners();
  }

  void _restoreFromJson(String raw) {
    try {
      final decoded = jsonDecode(raw) as Map<String, dynamic>;
      final accountsJson = decoded['accounts'];
      final restored = <String, LocalAccount>{};

      if (accountsJson is Map<String, dynamic>) {
        for (final entry in accountsJson.entries) {
          final value = entry.value;
          if (value is Map<String, dynamic>) {
            final account = LocalAccount.fromJson(value);
            if (account.email.isNotEmpty) restored[account.email] = account;
          }
        }
      }

      final current = _normalizeEmail(
        (decoded['currentEmail'] as String?) ?? '',
      );
      _accounts = restored;
      _currentEmail = restored.containsKey(current) ? current : null;
    } on FormatException {
      _accounts = <String, LocalAccount>{};
      _currentEmail = null;
    } on TypeError {
      _accounts = <String, LocalAccount>{};
      _currentEmail = null;
    }
  }
}

String? _validateCredentials(String email, String password) {
  if (!email.contains('@') || !email.contains('.')) {
    return '사용할 이메일을 정확히 적어줘.';
  }
  if (password.length < 6) {
    return '비밀번호는 6자 이상으로 해줘.';
  }
  return null;
}

String _normalizeEmail(String email) => email.trim().toLowerCase();

TrainingMode _trainingModeFromName(String? name) {
  for (final mode in TrainingMode.values) {
    if (mode.name == name) return mode;
  }
  return TrainingMode.pitchType;
}

int _readInt(Object? value, {required int fallback}) {
  if (value is int) return value;
  if (value is num) return value.round();
  if (value is String) return int.tryParse(value) ?? fallback;
  return fallback;
}
