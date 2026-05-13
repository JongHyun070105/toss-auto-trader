import 'package:flutter/material.dart';

import 'app_state.dart';

class BattersEyeScope extends InheritedNotifier<BattersEyeStore> {
  const BattersEyeScope({
    super.key,
    required BattersEyeStore store,
    required super.child,
  }) : super(notifier: store);

  static BattersEyeStore? maybeOf(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<BattersEyeScope>();
    return scope?.notifier;
  }

  static BattersEyeStore of(BuildContext context) {
    final scope = maybeOf(context);
    assert(scope != null, 'BattersEyeScope not found in widget tree.');
    return scope!;
  }
}
