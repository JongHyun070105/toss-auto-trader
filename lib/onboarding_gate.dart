import 'package:flutter/material.dart';

import 'app_state.dart';
import 'auth_screen.dart';
import 'home_screen.dart';
import 'placement_screen.dart';
import 'profile_screen.dart';

class BattersEyeScope extends InheritedNotifier<BattersEyeStore> {
  const BattersEyeScope({
    super.key,
    required BattersEyeStore store,
    required super.child,
  }) : super(notifier: store);

  static BattersEyeStore of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<BattersEyeScope>();
    assert(scope != null, 'BattersEyeScope not found in widget tree.');
    return scope!.notifier!;
  }
}

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
        OnboardingStage.auth => const AuthScreen(key: ValueKey('auth')),
        OnboardingStage.profile => const ProfileScreen(
          key: ValueKey('profile'),
        ),
        OnboardingStage.placement => const PlacementScreen(
          key: ValueKey('placement'),
        ),
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
