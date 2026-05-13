import 'package:flutter/material.dart';

import 'app_prefs.dart';
import 'app_state.dart';
import 'batters_eye_scope.dart';
import 'placement.dart';
import 'session.dart';

class AppCopy {
  AppCopy(this.language);

  final AppLanguage language;

  bool get _ko => language == AppLanguage.korean;

  String get appTitle => 'Batter’s Eye';
  String get loading => _ko ? '불러오는 중…' : 'Loading…';
  String get settings => _ko ? '설정' : 'Settings';
  String get close => _ko ? '닫기' : 'Close';
  String get save => _ko ? '저장' : 'Save';
  String get cancel => _ko ? '취소' : 'Cancel';
  String get logout => _ko ? '로그아웃' : 'Log out';
  String get sessions => _ko ? '세션' : 'Sessions';
  String get session => _ko ? '세션' : 'Session';
  String get focus => _ko ? '포커스' : 'Focus';
  String get level => _ko ? '레벨' : 'Level';
  String get reaction => _ko ? '반응' : 'Reaction';

  String get profileSummary => _ko ? '프로필 요약' : 'Profile summary';
  String get trainingModes => _ko ? '훈련 모드' : 'Training modes';
  String get latestReport => _ko ? '최근 리포트' : 'Latest report';
  String get howItWorks => _ko ? '동작 방식' : 'How it works';
  String get todayPitchMap => _ko ? '오늘의 피치 맵' : 'Today’s pitch map';
  String get pitchMapSubtitle => _ko
      ? '작은 존을 보고, 공의 길을 빠르게 읽는 감각을 쌓자.'
      : 'Track the zone and read the pitch path faster.';
  String get pitchLab => _ko ? '피치 랩' : 'Pitch Lab';
  String get liveMapLabel => _ko ? '실전 맵' : 'Live map';
  String get strikeZoneLabel => _ko ? '판정 존' : 'Strike zone';
  String get releaseLaneLabel => _ko ? '릴리스 경로' : 'Release lane';
  String get recommendedLevelLabel => _ko ? '추천 레벨' : 'Recommended level';
  String get sessionsBadgeLabel => _ko ? '세션' : 'Sessions';

  String homeGreeting(String name) => _ko
      ? '안녕, $name님. 오늘의 루틴을 바로 시작하자.'
      : 'Hi, $name. Start today’s routine.';

  String get homeIntro => _ko
      ? '계정, 프로필, 레벨 테스트, 훈련까지 한 번에 이어지는 일일 야구 루프.'
      : 'An account-based daily baseball loop from profile to placement to training.';

  String get introKicker => _ko ? '3분 온보딩' : '3-minute onboarding';
  String get introTitle => _ko
      ? '실전처럼 날아오는 공을 더 빨리 읽는 루틴을 시작해볼게요.'
      : 'Let’s start a routine that helps you read game-speed pitches earlier.';
  String get introBody => _ko
      ? '계정, 프로필, 레벨 테스트를 한 번만 마치면 바로 개인화된 첫 훈련으로 이어져요.'
      : 'Complete account, profile, and placement once, then jump into a personalized first routine.';
  String introStepCounter(int current, int total) => '$current / $total';
  String get introNextCta => _ko ? '다음 설명' : 'Next';
  String get introPrimaryCta => _ko ? '계정 만들고 시작하기' : 'Create account and start';
  String get introSecondaryCta => _ko ? '계정 화면으로 바로 가기' : 'Go straight to account';
  String get introBackCta => _ko ? '이전 설명' : 'Back';
  String get introStep1Title => _ko ? '릴리스부터 읽는 감각' : 'Read from release';
  String get introStep1Body => _ko
      ? '짧은 장면을 보고 구종, 존, 스윙 여부를 빠르게 판단하는 훈련이에요.'
      : 'You will watch short pitch scenes and quickly judge pitch type, zone, or swing decisions.';
  String get introStep2Title => _ko ? '지금 기준선을 먼저 확인' : 'Set your baseline first';
  String get introStep2Body => _ko
      ? '레벨 테스트 몇 문항만 풀면 놓치기 쉬운 코스와 반응 속도를 바로 읽어드려요.'
      : 'A short placement set quickly surfaces the lanes and reaction timing you miss most often.';
  String get introStep3Title => _ko ? 'AI 코치가 첫 7일을 정리' : 'AI coach maps your first week';
  String get introStep3Body => _ko
      ? '프로필과 테스트 결과를 바탕으로 Gemini가 첫 루틴을 차분하게 제안해드려요.'
      : 'Gemini uses your profile and placement result to calmly shape your first 7-day routine.';
  String get introStep1Metric => _ko ? '구종·존·스윙 판단' : 'Pitch · zone · swing read';
  String get introStep2Metric => _ko ? '짧은 5문항 기준선' : '5 quick baseline prompts';
  String get introStep3Metric => _ko ? '첫 7일 AI 루틴' : 'First 7-day AI plan';

  String get aiPlanTitle => _ko ? 'AI 코치가 첫 루틴을 짜는 중' : 'AI coach is building your first routine';
  String get aiPlanSubtitle => _ko
      ? '프로필과 레벨 테스트 결과를 바탕으로 첫 7일 플랜을 정리한다.'
      : 'The first 7-day plan is built from your profile and placement result.';
  String get aiPlanLoadingBody => _ko
      ? '강점 1개, 약점 1개, 이번 주 집중 포인트를 먼저 정리하고 있어.'
      : 'It is distilling one strength, one risk, and this week’s focus first.';
  String get aiPlanModelLabel => _ko ? '코치 모델' : 'Coach model';
  String get aiPlanStrengthLabel => _ko ? '현재 강점' : 'Current strength';
  String get aiPlanRiskLabel => _ko ? '지금 위험' : 'Current risk';
  String get aiPlanWhyNowLabel => _ko ? '왜 지금 이 루틴인가' : 'Why this routine now';
  String get aiPlanWeekLabel => _ko ? '첫 7일 플랜' : 'First 7-day plan';
  String get aiPlanPrimaryCta => _ko ? '이 플랜으로 시작' : 'Start with this plan';
  String get aiPlanMissingData => _ko
      ? '프로필이나 레벨 테스트 결과가 아직 없어. 이전 단계부터 다시 확인해줘.'
      : 'Profile or placement data is still missing. Please revisit the previous step.';
  String get aiPlanFallbackNote => _ko
      ? '아직 Gemini API 키가 없어서 임시 코치 로직으로 플랜을 만들고 있어.'
      : 'Gemini API key is not set yet, so a fallback coach plan is being used.';
  String get aiPlanLiveNote => _ko
      ? 'Gemini 2.5 Flash Lite 응답으로 개인화 플랜을 만들었다.'
      : 'This plan was generated from Gemini 2.5 Flash Lite.';
  String get homeAiSectionTitle => _ko ? 'AI 코치 해석' : 'AI coach read';
  String get homeAiSectionSubtitle => _ko
      ? '왜 이 모드를 추천하는지와 이번 주 포인트를 함께 본다.'
      : 'See why this mode is recommended and what this week should focus on.';

  String get heroFallbackBlurb => _ko
      ? '레벨 테스트를 마치면 개인 난도가 맞춰진다.'
      : 'Finish placement to lock in your personalized difficulty.';

  String get heroFallbackRecommendation => _ko
      ? '프로필과 테스트를 쌓으면 오늘의 추천이 더 정교해진다.'
      : 'Profile and placement data sharpen today’s recommendation.';

  String startModeLabel(TrainingMode mode) => _ko
      ? '시작 ${trainingModeLabel(mode)}'
      : 'Start ${trainingModeLabel(mode)}';

  String get profileSubtitle => _ko
      ? '이 정보가 추천 레벨과 훈련 톤을 맞춘다.'
      : 'These details tune your level and training tone.';

  String get trainingModesSubtitle => _ko
      ? '레벨 테스트 결과를 바탕으로 오늘의 모드를 고른다.'
      : 'Pick today’s mode from your placement results.';

  String get latestReportSubtitle => _ko
      ? '훈련 후 약점이 자동으로 기록된다.'
      : 'Your weak spots are recorded after each session.';

  String get howItWorksSubtitle => _ko
      ? '짧고 반복 가능해야 매일 돌아온다.'
      : 'Short loops keep the habit alive.';
  String get howItWorksStep1Title => _ko ? '프로필' : 'Profile';
  String get howItWorksStep1Body => _ko
      ? '나이·성별·포지션을 기록해 개인 기준을 만든다.'
      : 'Record age, gender, and position to set your baseline.';
  String get howItWorksStep2Title => _ko ? '레벨 테스트' : 'Placement test';
  String get howItWorksStep2Body => _ko
      ? '한 문제씩 풀며 시작 난도와 추천 모드를 정한다.'
      : 'Solve one question at a time to set difficulty and a recommended mode.';
  String get howItWorksStep3Title => _ko ? '반복 훈련' : 'Repeat training';
  String get howItWorksStep3Body => _ko
      ? '짧은 세션을 쌓고 리포트로 약점을 좁힌다.'
      : 'Stack short sessions and narrow weak spots from reports.';

  String get signOutTooltip => _ko ? '로그아웃' : 'Log out';
  String get settingsTooltip => _ko ? '설정' : 'Settings';

  String trainingModeLabel(TrainingMode mode) => switch (mode) {
    TrainingMode.pitchType => _ko ? '구종 읽기' : 'Pitch Read',
    TrainingMode.strikeZone => _ko ? '존 판정' : 'Strike Zone',
    TrainingMode.swingDecision => _ko ? '스윙 판단' : 'Swing Judge',
  };

  String trainingModeSubtitle(TrainingMode mode) => switch (mode) {
    TrainingMode.pitchType => _ko ? '구종을 빠르게 읽는 훈련' : 'Read pitch type faster',
    TrainingMode.strikeZone => _ko ? '공이 존 안인지 바로 판단' : 'Judge ball vs strike fast',
    TrainingMode.swingDecision => _ko ? '칠 공인지 참을 공인지 판단' : 'Decide swing vs take',
  };

  String trainingModeHero(TrainingMode mode) => switch (mode) {
    TrainingMode.pitchType => _ko
        ? '직구·슬라이더·커브를 빠르게 분류해봐.'
        : 'Classify fastball, slider, and curve quickly.',
    TrainingMode.strikeZone => _ko
        ? '스트라이크인지 볼인지 빠르게 판정해봐.'
        : 'Call ball or strike without hesitation.',
    TrainingMode.swingDecision => _ko
        ? '카운트와 코스를 보고 스윙 여부를 고르자.'
        : 'Read the count and course, then choose swing or take.',
  };

  String trainingModeFocus(TrainingMode mode) => switch (mode) {
    TrainingMode.pitchType => _ko ? '구종 인식 속도' : 'Pitch recognition speed',
    TrainingMode.strikeZone => _ko ? '존 판정 정확도' : 'Strike-zone accuracy',
    TrainingMode.swingDecision => _ko ? '스윙 디시전' : 'Swing decision',
  };

  String trainingModeAction(TrainingMode mode) => switch (mode) {
    TrainingMode.pitchType => _ko ? '구종 읽기 드릴' : 'Pitch Read drill',
    TrainingMode.strikeZone => _ko ? '존 판정 드릴' : 'Strike Zone drill',
    TrainingMode.swingDecision => _ko ? '스윙 판단 드릴' : 'Swing Judge drill',
  };

  String pitchLaneValue(String raw) => switch (raw) {
    'Straight heat' => _ko ? '직선형 직구 라인' : 'Straight heat',
    'Edge lane' => _ko ? '엣지 판정 라인' : 'Edge lane',
    'Decision lane' => _ko ? '스윙 판단 라인' : 'Decision lane',
    _ => raw,
  };

  String placementLevelLabel(PlacementLevel level) => switch (level) {
    PlacementLevel.rookie => _ko ? '루키' : 'Rookie',
    PlacementLevel.focused => _ko ? '포커스' : 'Focused',
    PlacementLevel.gameReady => _ko ? '게임 레디' : 'Game Ready',
    PlacementLevel.lockedIn => _ko ? '락인' : 'Locked In',
  };

  String placementLevelCoach(PlacementLevel level) => switch (level) {
    PlacementLevel.rookie => _ko
        ? '기초 판정 루틴부터 차근차근 쌓자.'
        : 'Start with a simple call routine and build up.',
    PlacementLevel.focused => _ko
        ? '한 가지 약점을 좁혀서 매일 반복하자.'
        : 'Narrow one weakness and repeat it daily.',
    PlacementLevel.gameReady => _ko
        ? '실전 감각은 좋아. 반응 속도를 더 줄이자.'
        : 'Game sense is solid. Trim the reaction time next.',
    PlacementLevel.lockedIn => _ko
        ? '좋아. 어려운 공을 섞어도 기준을 유지하자.'
        : 'Great. Keep the standard even as the pitches get tougher.',
  };

  String placementIntensity(PlacementLevel level) => switch (level) {
    PlacementLevel.rookie => _ko ? '하루 5분 · 정확도 우선' : '5 min daily · accuracy first',
    PlacementLevel.focused => _ko ? '하루 7분 · 약점 반복' : '7 min daily · repeat the weak spot',
    PlacementLevel.gameReady => _ko ? '하루 10분 · 속도 강화' : '10 min daily · speed up',
    PlacementLevel.lockedIn => _ko ? '하루 12분 · 실전 난도' : '12 min daily · game speed',
  };

  String placementRecommendation(PlacementResult result) {
    return _ko
        ? '${placementLevelLabel(result.level)} 레벨 · ${trainingModeFocus(result.recommendedMode)}부터 시작하자.'
        : '${placementLevelLabel(result.level)} level · start with ${trainingModeFocus(result.recommendedMode)}.';
  }

  String get placementTitle => _ko ? '레벨 테스트' : 'Placement test';
  String get placementIntro => _ko
      ? '공이 날아오는 장면을 보듯, 한 번에 하나씩 읽고 판단하자.'
      : 'Watch the pitch, read it once, and decide fast.';
  String get placementWarmup => _ko ? '릴리스 준비' : 'Release ready';
  String get placementQuestion => _ko ? '질문' : 'Question';
  String get placementResult => _ko ? '결과' : 'Result';
  String get placementStartPitch => _ko ? '투구 시작' : 'Start pitch';
  String get placementSaveResult => _ko ? '결과 저장' : 'Save result';
  String get placementSaved => _ko ? '저장 완료' : 'Saved';
  String get placementPrepLabel => _ko ? '준비' : 'Prep';
  String get placementFocusLabel => _ko ? '포커스' : 'Focus';
  String get placementZoneBoardLabel => _ko ? '판정 존' : 'Strike zone';
  String get placementReleaseLaneLabel => _ko ? '릴리스 라인' : 'Release lane';
  String get placementQuickHint => _ko
      ? '릴리스 직후의 첫 인상만 믿고, 가장 가까운 답을 골라보세요.'
      : 'Trust the first read after release and choose the closest answer.';
  String get placementSelectFirst => _ko ? '먼저 가장 가까운 답 하나를 골라주세요.' : 'Please choose the closest answer first.';
  String get placementViewResult => _ko ? '결과 보기' : 'View result';
  String get placementNextQuestion => _ko ? '다음 질문' : 'Next question';
  String placementCorrectFeedback(bool isCorrect, String correctChoice) => _ko
      ? (isCorrect ? '좋았어요. 판정이 정확했어요.' : '정답은 ${trainingChoiceLabel(correctChoice)}예요.')
      : (isCorrect ? 'Nice read. That call was correct.' : 'The correct answer is ${trainingChoiceLabel(correctChoice)}.');
  String get placementRecommendedResultTitle => _ko ? '추천 결과' : 'Recommended result';
  String get placementIntensityLabel => _ko ? '강도' : 'Intensity';
  String get placementRecommendedModeLabel => _ko ? '추천 모드' : 'Recommended mode';
  String get placementSaveAndGoHome => _ko ? '레벨 저장하고 홈으로' : 'Save level and go home';
  String get placementFlowTitle => _ko ? '진행 방식' : 'How it works';
  String get placementFlowBody => _ko
      ? '한 번에 한 문제씩 짧게 진행하고, 답을 고르면 바로 코치 피드백이 붙는다.'
      : 'Go one pitch at a time, then get instant coach feedback after each answer.';

  String placementStageLabel({
    required bool showPrompt,
    required bool hasResult,
    required int index,
    required int total,
  }) {
    if (hasResult) return placementResult;
    if (showPrompt) return '$placementQuestion ${index + 1}/$total';
    return placementWarmup;
  }

  String get authTitle => _ko
      ? '계정을 만들거나 로그인하면 프로필, 레벨, 훈련 기록이 한 흐름으로 이어져요.'
      : 'Create an account or log in to keep your profile, level, and training history in one flow.';
  String get authToggleSignUp => _ko ? '회원가입' : 'Sign up';
  String get authToggleLogin => _ko ? '로그인' : 'Log in';
  String get authEmailLabel => _ko ? '이메일' : 'Email';
  String get authPasswordLabel => _ko ? '비밀번호' : 'Password';
  String get authEmailHint => 'you@example.com';
  String get authPasswordHintSignup => _ko ? '6자 이상으로 입력해주세요' : 'At least 6 characters';
  String get authPasswordHintLogin => _ko ? '기존 비밀번호를 입력해주세요' : 'Enter your password';
  String get authJoinCta => _ko ? '회원가입하고 이어가기' : 'Sign up and continue';
  String get authLoginCta => _ko ? '로그인하고 이어가기' : 'Log in and continue';
  String get authSwitchToLogin => _ko ? '이미 계정이 있다면 로그인' : 'Already have an account? Log in';
  String get authSwitchToSignup => _ko ? '새 계정 만들기' : 'Create a new account';
  String get authHint => _ko
      ? '가입이 끝나면 프로필과 레벨 테스트를 차례대로 도와드릴게요.'
      : 'After sign-up, we will guide you through profile setup and placement.';
  String get authHintLogin => _ko
      ? '이 기기에 저장된 계정으로 이어서 진행할 수 있어요.'
      : 'You can continue with the account stored on this device.';
  String get authAccountReasonTitle => _ko ? '왜 계정이 필요한가요?' : 'Why is an account needed?';
  String get authAccountReasonBody => _ko
      ? '레벨, 반응 시간, 약점 카드를 계정에 연결해 두면 다음 훈련이 더 정확해져요.'
      : 'Keeping your level, reaction times, and weak spots on one account makes the next recommendation more accurate.';
  String get authSnackSignup => _ko ? '가입이 완료됐어요. 이어서 프로필을 설정해볼게요.' : 'Sign-up is complete. Let’s continue with your profile.';
  String get authSnackLogin => _ko ? '다시 만나서 반가워요. 프로필부터 이어서 볼게요.' : 'Welcome back. Let’s continue with your profile.';
  String get authErrorInvalidEmail => _ko ? '사용하실 이메일 주소를 정확히 입력해주세요.' : 'Please enter a valid email address.';
  String get authErrorWeakPassword => _ko ? '비밀번호는 6자 이상으로 입력해주세요.' : 'Password should be at least 6 characters.';
  String get authErrorEmailRequired => _ko ? '이메일을 입력해주세요.' : 'Please enter your email.';
  String get authErrorEmailFormat => _ko ? '이메일 형식을 다시 확인해주세요.' : 'That email format looks off.';
  String get authErrorPasswordRequired => _ko ? '비밀번호를 입력해주세요.' : 'Please enter your password.';

  String get profileTitle => _ko ? '프로필 설정' : 'Profile setup';
  String get profileIntro => _ko
      ? '나이, 성별, 포지션, 타석을 알려주시면 추천 레벨을 더 정확하게 맞춰드릴 수 있어요.'
      : 'Age, gender, position, and side help us sharpen the recommendation.';
  String get profileNameLabel => _ko ? '이름 / 닉네임' : 'Name / nickname';
  String get profileNameHint => _ko ? '예: 종현' : 'e.g. Jonghyun';
  String get profileAgeLabel => _ko ? '나이' : 'Age';
  String get profileAgeHint => _ko ? '예: 23' : 'e.g. 23';
  String get profileGenderLabel => _ko ? '성별' : 'Gender';
  String get profilePositionLabel => _ko ? '포지션' : 'Position';
  String get profileBattingSideLabel => _ko ? '타석' : 'Batting side';
  String get profileExperienceLabel => _ko ? '경험치' : 'Experience';
  String get profileGoalLabel => _ko ? '오늘의 목표' : 'Today’s goal';
  String get profileNote => _ko
      ? '이 정보는 레벨 추천과 훈련 카드 개인화에만 사용돼요.'
      : 'We only use this to personalize level and training cards.';
  String get profileRecommendationTitle => _ko ? '추천이 어떻게 달라지나요?' : 'How does this change the recommendation?';
  String get profileRecommendationBody => _ko
      ? '나이, 타석, 포지션, 목표가 맞아질수록 레벨과 모드 추천이 더 정교해져요.'
      : 'Age, side, position, and goal make level and mode recommendations more precise.';
  String get profileSaveCta => _ko ? '프로필 저장하고 레벨 테스트로' : 'Save profile and go to placement';
  String get profileSaving => _ko ? '저장 중…' : 'Saving…';
  String get profileErrorName => _ko ? '이름이나 닉네임을 입력해주세요.' : 'Please enter a name.';
  String get profileErrorAge => _ko ? '나이는 숫자로 입력해주세요.' : 'Please enter a number.';
  String get profileErrorAgeRequired => _ko ? '나이를 입력해주세요.' : 'Please enter your age.';
  String get profileErrorAgePositive => _ko ? '0보다 큰 숫자를 입력해주세요.' : 'Enter a number greater than 0.';
  String get profileErrorAgeRange => _ko ? '나이를 다시 확인해주세요.' : 'Please double-check the age.';

  List<ProfileChoice> get genderChoices => const [
        ProfileChoice('male', '남성', 'Male'),
        ProfileChoice('female', '여성', 'Female'),
        ProfileChoice('nonbinary', '논바이너리', 'Non-binary'),
        ProfileChoice('unspecified', '응답 안 함', 'Prefer not to say'),
      ];

  List<ProfileChoice> get positionChoices => const [
        ProfileChoice('batter', '타자', 'Batter'),
        ProfileChoice('pitcher', '투수', 'Pitcher'),
        ProfileChoice('catcher', '포수', 'Catcher'),
        ProfileChoice('infielder', '내야수', 'Infielder'),
        ProfileChoice('outfielder', '외야수', 'Outfielder'),
        ProfileChoice('coach', '코치', 'Coach'),
      ];

  List<ProfileChoice> get battingSideChoices => const [
        ProfileChoice('left', '좌타', 'Left'),
        ProfileChoice('right', '우타', 'Right'),
        ProfileChoice('switch', '스위치', 'Switch'),
        ProfileChoice('unknown', '모름', 'Unknown'),
      ];

  List<ProfileChoice> get experienceChoices => const [
        ProfileChoice('beginner', '입문', 'Beginner'),
        ProfileChoice('1_2', '1~2년', '1–2 years'),
        ProfileChoice('3_5', '3~5년', '3–5 years'),
        ProfileChoice('5_plus', '5년+', '5+ years'),
      ];

  List<ProfileChoice> get goalChoices => const [
        ProfileChoice('pitch_recognition', '구종 인식', 'Pitch recognition'),
        ProfileChoice('zone_calls', '존 판정', 'Strike-zone calls'),
        ProfileChoice('swing_decision', '스윙 디시전', 'Swing decision'),
        ProfileChoice('game_feel', '실전 감각', 'Game feel'),
        ProfileChoice('reaction_speed', '반응 속도', 'Reaction speed'),
      ];

  String profileGenderValue(String raw) => _choiceLabel(genderChoices, raw);
  String profilePositionValue(String raw) => _choiceLabel(positionChoices, raw);
  String profileBattingSideValue(String raw) => _choiceLabel(battingSideChoices, raw);
  String profileExperienceValue(String raw) => _choiceLabel(experienceChoices, raw);
  String profileGoalValue(String raw) => _choiceLabel(goalChoices, raw);

  String normalizeProfileGender(String raw) => _choiceCode(genderChoices, raw);
  String normalizeProfilePosition(String raw) => _choiceCode(positionChoices, raw);
  String normalizeProfileBattingSide(String raw) => _choiceCode(battingSideChoices, raw);
  String normalizeProfileExperience(String raw) => _choiceCode(experienceChoices, raw);
  String normalizeProfileGoal(String raw) => _choiceCode(goalChoices, raw);

  List<String> profileChipTexts(UserProfile profile) => [
        if (profile.age > 0) _ko ? '${profile.age}세' : '${profile.age}y',
        profileGenderValue(profile.gender),
        profilePositionValue(profile.position),
        profileBattingSideValue(profile.battingSide),
        profileExperienceValue(profile.experience),
        profileGoalValue(profile.goal),
      ];

  String _choiceLabel(List<ProfileChoice> choices, String raw) {
    for (final choice in choices) {
      if (raw == choice.code || raw == choice.ko || raw == choice.en) {
        return choice.label(language);
      }
    }
    return raw;
  }

  String _choiceCode(List<ProfileChoice> choices, String raw) {
    for (final choice in choices) {
      if (raw == choice.code || raw == choice.ko || raw == choice.en) {
        return choice.code;
      }
    }
    return raw;
  }

  String get settingsHeader => _ko ? '설정' : 'Settings';
  String get settingsSubtitle => _ko
      ? '화이트 모드와 다크 모드, 한국어와 영어를 바꿀 수 있다.'
      : 'Switch between light/dark and Korean/English.';
  String get themeSection => _ko ? '테마' : 'Theme';
  String get themeSectionSubtitle => _ko
      ? '화이트 모드와 다크 모드를 전환할 수 있다.'
      : 'Toggle between light and dark modes.';
  String get languageSection => _ko ? '언어' : 'Language';
  String get lightThemeLabel => _ko ? '화이트' : 'Light';
  String get darkThemeLabel => _ko ? '다크' : 'Dark';
  String get koreanLanguageLabel => _ko ? '한국어' : 'Korean';
  String get englishLanguageLabel => _ko ? '영어' : 'English';
  String get lightThemeDescription => _ko ? '밝은 배경 + 다크 카드' : 'Bright shell with dark cards';
  String get darkThemeDescription => _ko ? '올 다크 스포츠 모드' : 'Full dark sports mode';
  String get languageDescription => _ko
      ? '화면 문구와 훈련 카드를 선택한 언어로 보여준다.'
      : 'Show the screen copy and drills in your selected language.';
  String get settingsPreviewLabel => _ko ? '미리보기' : 'Preview';

  String get reportAccuracyLabel => _ko ? '정확도' : 'Accuracy';
  String get reportReactionLabel => _ko ? '반응' : 'Reaction';
  String get reportWeakSpotLabel => _ko ? '약점' : 'Weak spot';
  String get recommendedBadgeLabel => _ko ? '추천' : 'Recommended';
  String get emptyProfileTitle => _ko ? '아직 프로필이 없어' : 'No profile yet';
  String get emptyProfileBody => _ko
      ? '프로필을 입력하면 나이·성별·포지션에 맞게 레벨과 루틴을 더 잘 추천할 수 있다.'
      : 'Fill out your profile so the app can tune level and routine recommendations.';
  String get emptyReportTitle => _ko ? '아직 세션이 없어' : 'No sessions yet';
  String get emptyReportBody => _ko
      ? '훈련을 한 번 끝내면 정확도와 약점이 자동으로 기록된다.'
      : 'Finish one session to record accuracy and weak spots.';

  String trainingReportCoachLine(TrainingReport? report) {
    if (report == null || report.totalRounds == 0) {
      return _ko ? '아직 기록이 없어. 첫 세션을 짧게 끝내자.' : 'No sessions yet. Finish a short first run.';
    }
    if (report.accuracy >= 0.8) {
      return _ko ? '좋아. 같은 기준으로 난도를 한 단계 올려보자.' : 'Nice. Raise the difficulty one step.';
    }
    return _ko
        ? '다음 세션은 ${trainingRoundWeakSpot(report.primaryWeakSpot)} 하나만 잡고 가자.'
        : 'Next session, focus on ${trainingRoundWeakSpot(report.primaryWeakSpot)}.';
  }

  String trainingRoundWeakSpot(String tag) => switch (tag) {
    'high heater' => _ko ? '높은 직구' : 'high heater',
    'late sweep' => _ko ? '늦게 휘는 슬라이더' : 'late sweep',
    'big breaker' => _ko ? '큰 낙차의 변화구' : 'big breaker',
    'inside heater' => _ko ? '몸쪽 직구' : 'inside heater',
    'back-foot breaker' => _ko ? '발쪽 변화구' : 'back-foot breaker',
    'rainbow curve' => _ko ? '큰 커브' : 'rainbow curve',
    'high in-zone' => _ko ? '높은 존' : 'high in-zone',
    'low-away chase' => _ko ? '낮고 바깥쪽 공' : 'low-away chase',
    'middle heater' => _ko ? '가운데 직구' : 'middle heater',
    'backdoor edge' => _ko ? '백도어 공' : 'backdoor edge',
    'dirt chase' => _ko ? '바닥 공' : 'dirt chase',
    'high miss' => _ko ? '높이 벗어난 공' : 'high miss',
    'green light count' => _ko ? '유리한 카운트' : 'green light count',
    'chase pitch' => _ko ? '쫓아가면 안 되는 공' : 'chase pitch',
    'hitter count' => _ko ? '타자 유리 카운트' : 'hitter count',
    'borderline chase' => _ko ? '애매한 chase 공' : 'borderline chase',
    'belt-high attack' => _ko ? '벨트 높이 공' : 'belt-high attack',
    'buried breaker' => _ko ? '깊게 묻힌 변화구' : 'buried breaker',
    _ => tag,
  };

  String get resultSessionComplete => _ko ? '세션 완료' : 'Session complete';
  String get resultAccuracyLabel => _ko ? '정확도' : 'Accuracy';
  String get resultAvgReactionLabel => _ko ? '평균 반응' : 'Avg RT';
  String get resultRoundsLabel => _ko ? '라운드' : 'Rounds';
  String get resultWeakSpotLabel => _ko ? '약점' : 'Weak spot';
  String get resultCoachNote => _ko ? '코치 노트' : 'Coach note';
  String get resultBackToDashboard => _ko ? '대시보드로 돌아가기' : 'Back to dashboard';
  String resultSessionLine(TrainingSummary summary) => _ko
      ? '이번 세션은 ${trainingModeLabel(summary.mode)} 중심으로 진행했고, 흔들린 지점을 바로 모아봤어요.'
      : 'This session focused on ${trainingModeLabel(summary.mode)} and surfaced where the read drifted.';
  String get resultNextSteps => _ko ? '다음 스텝' : 'Next steps';
  String resultNextStep(TrainingMode mode) => switch (mode) {
    TrainingMode.pitchType => _ko
        ? '다음에는 더 빠른 직구와 느린 브레이킹볼을 섞어서 다시 읽어보면 좋아요.'
        : 'Next, mix in faster heaters and slower breakers.',
    TrainingMode.strikeZone => _ko
        ? '바깥쪽과 높은 공을 조금 더 섞어서 chase 위험을 다시 확인해보세요.'
        : 'Mix more edge and high pitches to test chase risk.',
    TrainingMode.swingDecision => _ko
        ? '2스트라이크 상황을 늘려서 참아야 할 공을 더 많이 보는 연습을 해보세요.'
        : 'Add more two-strike reps and train the take.',
  };

  String get trainingActionReady => _ko ? '투구 시작' : 'Start pitch';
  String get trainingTrackReleaseHint => _ko
      ? '릴리스 직후의 첫 궤적을 보고, 판단 창이 열릴 때 답을 골라보세요.'
      : 'Track the first flight off release, then answer when the decision window opens.';
  String get trainingPromptSupport => _ko
      ? '지금 본 인상에 가장 가까운 답 하나를 골라주세요.'
      : 'Choose the single answer that best matches what you saw.';
  String get trainingAnsweredLabel => _ko ? '응답' : 'Answered';
  String get trainingAccuracyLabel => _ko ? '정확도' : 'Accuracy';
  String get trainingFocusLabel => _ko ? '포커스' : 'Focus';
  String get trainingPhaseLabel => _ko ? '단계' : 'Phase';
  String get trainingReleaseLabel => _ko ? '릴리스' : 'Release';
  String get trainingPlateLabel => _ko ? '플레이트' : 'Plate';
  String get trainingSpeedLabel => _ko ? '체감 구속' : 'Speed cue';
  String get trainingWindowLabel => _ko ? '판단 창' : 'Decision window';
  String get trainingLaneLabel => _ko ? '비행 라인' : 'Flight lane';
  String trainingPhaseValue(bool promptVisible) =>
      promptVisible ? (_ko ? '판단' : 'READ') : (_ko ? '추적' : 'LOCK');
  String trainingSceneLine(bool promptVisible) => _ko
      ? (promptVisible ? '지금 본 궤적으로 가장 가까운 답을 골라주세요.' : '릴리스 포인트를 따라가면서 판단 창이 열릴 때까지 기다려보세요.')
      : (promptVisible
            ? 'Choose the answer that best matches the flight you just saw.'
            : 'Track the release point and wait for the decision window.');
  String trainingHeaderLine(TrainingMode mode) => _ko
      ? '${trainingModeLabel(mode)}만 짧고 진하게 반복해서 오늘의 약점을 좁혀볼게요.'
      : 'Repeat ${trainingModeLabel(mode)} in short, focused reps to narrow today’s weak spot.';
  String trainingAppBarTitle(TrainingMode mode, int current, int total) =>
      '${trainingModeLabel(mode)} · $current/$total';
  String trainingFeedbackTitle(bool isCorrect) =>
      _ko ? (isCorrect ? '좋은 판단이었어요' : '다시 한 번 읽어볼게요') : (isCorrect ? 'Good read' : 'Let’s re-read that one');
  String trainingCorrectAnswer(String choice) => _ko
      ? '정답은 ${trainingChoiceLabel(choice)}예요.'
      : 'The correct answer is ${trainingChoiceLabel(choice)}.';
  String trainingNextButton(bool isLastRound) =>
      _ko ? (isLastRound ? '세션 마무리' : '다음 공') : (isLastRound ? 'Finish session' : 'Next pitch');
  String get trainingInsightTitle => _ko ? '이번 공 포인트' : 'Pitch note';

  String trainingChoiceLabel(String raw) => switch (raw) {
    'Fastball' => _ko ? '직구' : 'Fastball',
    'Slider' => _ko ? '슬라이더' : 'Slider',
    'Curve' => _ko ? '커브' : 'Curve',
    'Strike' => _ko ? '스트라이크' : 'Strike',
    'Ball' => _ko ? '볼' : 'Ball',
    'Swing' => _ko ? '스윙' : 'Swing',
    'Take' => _ko ? '참기' : 'Take',
    _ => raw,
  };

  String _trainingRoundKey(String id) {
    final parts = id.split('-');
    if (parts.length >= 4) {
      return parts.sublist(2).join('-');
    }
    return id;
  }

  String trainingRoundTitle(TrainingRound round) => switch (_trainingRoundKey(round.id)) {
    'pitch-fastball-letters' => _ko ? '높은 코스 96마일 직구' : '96 mph heater at the letters',
    'pitch-slider-away' => _ko ? '바깥쪽으로 크게 휘는 슬라이더' : 'Glove-side slider sweeping away',
    'pitch-curve-dropping' => _ko ? '급하게 떨어지는 12-6 커브' : 'Hard-dropping 12–6 breaker',
    'pitch-heater-inside' => _ko ? '몸쪽 높은 직구' : 'Inside heater, chest high',
    'pitch-backfoot' => _ko ? '발쪽으로 파고드는 브레이킹볼' : 'Back-foot breaker',
    'pitch-big-arc' => _ko ? '큰 아크의 커브' : 'Big rainbow curve',
    'zone-high-tight' => _ko ? '몸쪽 높은 코스' : 'High and tight',
    'zone-low-away' => _ko ? '낮고 바깥쪽으로 살짝 빠짐' : 'Low away, just off the plate',
    'zone-middle-middle' => _ko ? '가운데로 몰린 직구' : 'Middle-middle heater',
    'zone-backdoor' => _ko ? '끝에서 걸치는 백도어' : 'Backdoor edge',
    'zone-bounce' => _ko ? '바닥으로 튀는 공' : 'Bouncer in the dirt',
    'zone-letters-off' => _ko ? '높게 빠지는 공' : 'Letters that miss high',
    'swing-2-0-heater' => _ko ? '2-0 카운트, 가운데-몸쪽 직구' : '2-0 count, middle-in heater',
    'swing-0-2-slider' => _ko ? '0-2 카운트, 존 아래 슬라이더' : '0-2 count, slider below the zone',
    'swing-3-1-fastball' => _ko ? '3-1 카운트, 스트라이크용 직구' : '3-1 count, get-me-over fastball',
    'swing-1-2-breaking' => _ko ? '1-2 카운트, 플레이트 밖 변화구' : '1-2 count, breaking ball off the plate',
    'swing-belt-high' => _ko ? '벨트 높이 직구' : 'Belt-high heater',
    'swing-buried-curve' => _ko ? '묻히는 커브볼' : 'Buried curveball',
    _ => round.title,
  };

  String trainingRoundPrompt(TrainingRound round) => switch (round.mode) {
    TrainingMode.pitchType => _ko ? '이 공의 구종은?' : 'What pitch is it?',
    TrainingMode.strikeZone => _ko ? '스트라이크일까?' : 'Strike or ball?',
    TrainingMode.swingDecision => _ko ? '스윙할까?' : 'Swing or take?',
  };

  String trainingRoundCoachNote(TrainingRound round) => switch (_trainingRoundKey(round.id)) {
    'pitch-fastball-letters' => _ko ? '높은 직구는 릴리스 직후부터 눈을 놓치지 않는 게 핵심이야.' : 'Stay on the release point immediately to read the high heater.',
    'pitch-slider-away' => _ko ? '슬라이더는 마지막에 휘는 타이밍을 끝까지 따라가보자.' : 'Track the late sweep all the way to the plate.',
    'pitch-curve-dropping' => _ko ? '커브는 초반에 팔 스피드만 보고 속지 말고 낙차를 확인해.' : 'Do not trust arm speed alone; confirm the drop.',
    'pitch-heater-inside' => _ko ? '몸쪽 빠른 공은 시야가 흔들리니 시작점을 먼저 보자.' : 'Inside velocity can rush your eyes, so lock onto the start point first.',
    'pitch-backfoot' => _ko ? '발쪽으로 떨어지는 공은 끝까지 참는 훈련이 중요해.' : 'Train yourself to hold on pitches that dive toward the back foot.',
    'pitch-big-arc' => _ko ? '곡선이 큰 공은 처음 속도보다 회전과 낙차를 같이 보자.' : 'On big-arc curves, read spin and drop together instead of raw speed.',
    'zone-high-tight' => _ko ? '몸쪽 높은 공은 생각보다 존 안에 들어올 수 있어.' : 'High-and-tight pitches can still clip the zone more often than you think.',
    'zone-low-away' => _ko ? '낮고 바깥쪽 공은 마지막에 속기 쉬우니 참는 습관을 확인해.' : 'Low-away pitches tempt late chases, so trust the finish point.',
    'zone-middle-middle' => _ko ? '가운데 공은 더 자신 있게 스트라이크로 잡아도 좋아.' : 'Call the middle heater with confidence.',
    'zone-backdoor' => _ko ? '끝에서 들어오는 공은 존에 걸리는 순간을 놓치지 말자.' : 'Do not miss the moment a backdoor pitch catches the edge.',
    'zone-bounce' => _ko ? '낮게 꺾여 떨어지는 공은 초반 릴리스만 보고 속지 말자.' : 'Do not get fooled by the early look on pitches that bury late.',
    'zone-letters-off' => _ko ? '너무 높은 공은 마지막 위치를 보고 확실히 걸러내자.' : 'Confirm the finish and spit on pitches that stay too high.',
    'swing-2-0-heater' => _ko ? '유리한 카운트에서는 자신 있게 스윙하는 연습이 필요해.' : 'In a hitter’s count, train yourself to attack with conviction.',
    'swing-0-2-slider' => _ko ? '투 스트라이크에서는 존 밖 공을 끝까지 참는 게 핵심이야.' : 'With two strikes, the key is still taking pitches that stay off the zone.',
    'swing-3-1-fastball' => _ko ? '좋은 카운트의 한가운데 공은 놓치면 아까워.' : 'Do not waste a center-cut fastball in a hitter’s count.',
    'swing-1-2-breaking' => _ko ? '애매한 공은 존을 끝까지 확인한 뒤 결정하자.' : 'On borderline breakers, confirm the zone all the way through.',
    'swing-belt-high' => _ko ? '스트라이크 존 한복판은 공격적으로 가져가도 좋아.' : 'Attack belt-high strikes through the middle aggressively.',
    'swing-buried-curve' => _ko ? '바닥으로 떨어지는 공은 낚이지 않고 참는 습관을 만든다.' : 'Build the habit of taking breaking balls that die in the dirt.',
    _ => round.coachingPoint,
  };

  String placementQuestionTitle(PlacementQuestion question) => switch (question.id) {
    'release-fastball' => _ko ? '릴리스가 빠르고 공이 떠오른다' : 'Quick release with rising life',
    'low-away-zone' => _ko ? '낮고 바깥쪽으로 살짝 빠지는 공' : 'Low-away pitch fading just off',
    'hitter-count' => _ko ? '3-1 카운트, 가운데 높은 직구' : '3-1 count, elevated middle heater',
    'breaking-dirt' => _ko ? '0-2 카운트, 바닥으로 떨어지는 변화구' : '0-2 count, breaking ball into the dirt',
    'backdoor-edge' => _ko ? '바깥에서 안으로 걸치는 백도어 공' : 'Backdoor pitch clipping the edge',
    _ => question.title,
  };

  String placementQuestionPrompt(PlacementQuestion question) => switch (question.id) {
    'release-fastball' => _ko ? '가장 가능성이 높은 구종은?' : 'Which pitch type is most likely?',
    'low-away-zone' => _ko ? '존 안으로 볼까?' : 'Is it in the zone?',
    'hitter-count' => _ko ? '이 상황의 기본 선택은?' : 'What is the default decision here?',
    'breaking-dirt' => _ko ? '참아야 할까?' : 'Should you take it?',
    'backdoor-edge' => _ko ? '판정은?' : 'What is the call?',
    _ => question.prompt,
  };

  String placementQuestionCoachNote(PlacementQuestion question) => switch (question.id) {
    'release-fastball' => _ko ? '직구는 초반 궤적이 가장 곧고 빠르게 보인다.' : 'Fastballs look the straightest and quickest right out of release.',
    'low-away-zone' => _ko ? '낮은 바깥쪽은 끝에서 속기 쉬운 대표 chase 코스다.' : 'Low away is a classic chase lane that fools hitters late.',
    'hitter-count' => _ko ? '유리한 카운트의 좋은 공은 과감하게 공격한다.' : 'In a hitter’s count, attack a good pitch with intent.',
    'breaking-dirt' => _ko ? '투 스트라이크에서도 바닥 공은 기준을 지켜야 한다.' : 'Even with two strikes, hold your line on pitches in the dirt.',
    'backdoor-edge' => _ko ? '끝에서 들어오는 공은 마지막 위치까지 본다.' : 'On backdoor action, trust the final location.',
    _ => question.coachNote,
  };

  String trainingSummaryEncouragement(TrainingSummary summary) {
    if (summary.totalRounds == 0) {
      return _ko ? '아직 기록이 없어요. 첫 세션을 가볍게 시작해볼까요?' : 'No session is logged yet. Let’s start with a short first run.';
    }
    if (summary.accuracy >= 0.8) {
      return _ko
          ? '좋아요. 이 감각을 유지한 채 더 어려운 투구까지 천천히 확장해볼게요.'
          : 'Nice. Let’s carry this feel into tougher pitches.';
    }
    return _ko
        ? '다음 5분은 ${trainingRoundWeakSpot(summary.primaryWeakSpot)}에만 집중해보면 좋아요.'
        : 'For the next 5 minutes, focus on ${trainingRoundWeakSpot(summary.primaryWeakSpot)}.';
  }
}

extension AppCopyX on BuildContext {
  AppCopy get copy =>
      AppCopy(BattersEyeScope.maybeOf(this)?.language ?? AppLanguage.korean);
}

class ProfileChoice {
  const ProfileChoice(this.code, this.ko, this.en);

  final String code;
  final String ko;
  final String en;

  String label(AppLanguage language) =>
      language == AppLanguage.korean ? ko : en;
}
