import 'package:flutter/material.dart';

import 'ai_plan_screen.dart';
import 'app_state.dart';
import 'batters_eye_scope.dart';
import 'auth_screen.dart';
import 'home_screen.dart';
import 'onboarding_intro_screen.dart';
import 'placement_screen.dart';
import 'profile_screen.dart';

class OnboardingGate extends StatelessWidget {
  const OnboardingGate({super.key});

  @override
  Widget build(BuildContext context) {
    final store = BattersEyeScope.of(context);

    if (!store.isLoaded) {
      return const _LoadingScreen();
    }

    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 260),
      switchInCurve: Curves.easeOut,
      switchOutCurve: Curves.easeIn,
      child: switch (store.stage) {
        OnboardingStage.intro => const OnboardingIntroScreen(
          key: ValueKey('intro'),
        ),
        OnboardingStage.auth => const AuthScreen(key: ValueKey('auth')),
        OnboardingStage.profile => const ProfileScreen(
          key: ValueKey('profile'),
        ),
        OnboardingStage.placement => const PlacementScreen(
          key: ValueKey('placement'),
        ),
        OnboardingStage.aiPlan => const AiPlanScreen(key: ValueKey('aiPlan')),
        OnboardingStage.dashboard => const HomeScreen(
          key: ValueKey('dashboard'),
        ),
      },
    );
  }
}

class _LoadingScreen extends StatelessWidget {
  const _LoadingScreen();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: DecoratedBox(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [Color(0xFF07111F), Color(0xFF0B1730)],
          ),
        ),
        child: Center(child: CircularProgressIndicator()),
      ),
    );
  }
}
