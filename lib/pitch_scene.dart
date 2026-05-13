import 'dart:math' as math;
import 'dart:ui';

import 'package:flutter/material.dart';

import 'app_copy.dart';
import 'app_theme.dart';
import 'session.dart';

class PitchMotionSpec {
  const PitchMotionSpec({
    required this.release,
    required this.control1,
    required this.control2,
    required this.plate,
    required this.duration,
    required this.revealAt,
    required this.laneLabel,
  });

  final Offset release;
  final Offset control1;
  final Offset control2;
  final Offset plate;
  final Duration duration;
  final double revealAt;
  final String laneLabel;

  Offset samplePoint(Size size, double progress) {
    final t = Curves.easeInCubic.transform(progress.clamp(0.0, 1.0));
    final p0 = _scale(release, size);
    final p1 = _scale(control1, size);
    final p2 = _scale(control2, size);
    final p3 = _scale(plate, size);
    return _cubicBezier(p0, p1, p2, p3, t);
  }

  double ballRadius(double progress) {
    final t = Curves.easeOut.transform(progress.clamp(0.0, 1.0));
    return lerpDouble(13, 25, t)!;
  }

  double trailOpacity(double progress) {
    final t = progress.clamp(0.0, 1.0);
    return lerpDouble(0.34, 0.10, t)!;
  }

  int estimatedSpeedMph() {
    final ms = duration.inMilliseconds.clamp(900, 1080);
    final t = (ms - 900) / 180;
    return lerpDouble(97, 82, t)!.round();
  }

  int decisionWindowMs() {
    return ((1 - revealAt) * duration.inMilliseconds).round();
  }
}

PitchMotionSpec pitchMotionForRound(TrainingRound round) {
  final seed = round.id.hashCode ^ round.title.hashCode;
  double wobble(int shift, double amplitude) {
    final raw = ((seed >> shift) & 0xFF) / 255.0;
    return (raw - 0.5) * amplitude;
  }

  final lateral = wobble(0, 0.14);
  final lift = wobble(8, 0.06);
  final breakBias = wobble(16, 0.12);
  final pace = wobble(24, 0.08);

  return switch (round.mode) {
    TrainingMode.pitchType => PitchMotionSpec(
      release: _clamped(0.80 + lateral * 0.25, 0.12 + lift),
      control1: _clamped(0.72 + lateral * 0.20, 0.24 + lift * 0.75),
      control2: _clamped(0.60 + breakBias * 0.6, 0.54 + lift * 0.5),
      plate: _clamped(0.50 + breakBias * 0.35, 0.88),
      duration: Duration(milliseconds: 940 + (pace * 120).round()),
      revealAt: 0.55,
      laneLabel: 'Straight heat',
    ),
    TrainingMode.strikeZone => PitchMotionSpec(
      release: _clamped(0.78 + lateral * 0.15, 0.11 + lift),
      control1: _clamped(0.69 + lateral * 0.18, 0.26 + lift * 0.7),
      control2: _clamped(0.54 + breakBias * 0.9, 0.58 + lift * 0.45),
      plate: _clamped(0.50 + breakBias * 0.50, 0.90),
      duration: Duration(milliseconds: 1020 + (pace * 100).round()),
      revealAt: 0.59,
      laneLabel: 'Edge lane',
    ),
    TrainingMode.swingDecision => PitchMotionSpec(
      release: _clamped(0.79 + lateral * 0.20, 0.12 + lift),
      control1: _clamped(0.71 + lateral * 0.16, 0.25 + lift * 0.75),
      control2: _clamped(0.57 + breakBias * 0.75, 0.56 + lift * 0.5),
      plate: _clamped(0.50 + breakBias * 0.42, 0.89),
      duration: Duration(milliseconds: 980 + (pace * 110).round()),
      revealAt: 0.57,
      laneLabel: 'Decision lane',
    ),
  };
}

class PitchScene extends StatelessWidget {
  const PitchScene({
    super.key,
    required this.round,
    required this.motion,
    required this.progress,
    required this.promptVisible,
    required this.answered,
    required this.selectedIndex,
  });

  final TrainingRound round;
  final PitchMotionSpec motion;
  final double progress;
  final bool promptVisible;
  final bool answered;
  final int? selectedIndex;

  @override
  Widget build(BuildContext context) {
    final copy = context.copy;
    final accent = _accentForMode(round.mode);
    final icon = _iconForMode(round.mode);
    final outcomeColor = answered
        ? (selectedIndex == round.correctIndex
              ? const Color(0xFF84F58E)
              : const Color(0xFFFF8FA3))
        : accent;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(26),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [accent.withValues(alpha: 0.18), const Color(0xFF0D1B31)],
        ),
        border: Border.all(color: context.panelBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: accent.withValues(alpha: 0.16),
                  shape: BoxShape.circle,
                ),
                child: Icon(icon, color: accent),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      copy.trainingRoundTitle(round),
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      copy.trainingSceneLine(promptVisible),
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: Colors.white.withValues(alpha: 0.72),
                      ),
                    ),
                  ],
                ),
              ),
              _SceneStatPill(
                label: copy.trainingPhaseLabel,
                value: copy.trainingPhaseValue(promptVisible),
              ),
            ],
          ),
          const SizedBox(height: 16),
          AspectRatio(
            aspectRatio: 1.62,
            child: LayoutBuilder(
              builder: (context, constraints) {
                final size = Size(constraints.maxWidth, constraints.maxHeight);
                final ballCenter = motion.samplePoint(size, progress);
                final ballRadius = motion.ballRadius(progress);

                return Stack(
                  clipBehavior: Clip.none,
                  children: [
                    Positioned.fill(
                      child: RepaintBoundary(
                        child: CustomPaint(
                          painter: _PitchFieldPainter(
                            round: round,
                            motion: motion,
                            progress: progress,
                            accent: accent,
                            outcomeColor: outcomeColor,
                            promptVisible: promptVisible,
                            answered: answered,
                            selectedIndex: selectedIndex,
                          ),
                        ),
                      ),
                    ),
                    Positioned(
                      key: const ValueKey('pitchBall'),
                      left: ballCenter.dx - ballRadius,
                      top: ballCenter.dy - ballRadius,
                      child: _PitchBall(
                        diameter: ballRadius * 2,
                        accent: outcomeColor,
                        progress: progress,
                      ),
                    ),
                    Positioned(
                      left: 14,
                      top: 14,
                      child: _SceneStatPill(
                        label: copy.trainingFocusLabel,
                        value: copy.trainingModeFocus(round.mode),
                      ),
                    ),
                    Positioned(
                      right: 14,
                      bottom: 14,
                      child: _SceneStatPill(
                        label: copy.trainingAccuracyLabel,
                        value: '${(progress * 100).round()}%',
                      ),
                    ),
                  ],
                );
              },
            ),
          ),
          const SizedBox(height: 12),
          Text(
            copy.trainingSceneLine(promptVisible),
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.70),
              height: 1.45,
            ),
          ),
        ],
      ),
    );
  }
}

class _PitchBall extends StatelessWidget {
  const _PitchBall({
    required this.diameter,
    required this.accent,
    required this.progress,
  });

  final double diameter;
  final Color accent;
  final double progress;

  @override
  Widget build(BuildContext context) {
    final seamRotation = progress * math.pi * 1.15;

    return Transform.rotate(
      angle: seamRotation,
      child: Container(
        width: diameter,
        height: diameter,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: RadialGradient(
            center: const Alignment(-0.35, -0.35),
            colors: [
              Colors.white,
              Color.lerp(Colors.white, accent, 0.18)!,
              accent.withValues(alpha: 0.95),
            ],
          ),
          boxShadow: [
            BoxShadow(
              color: accent.withValues(alpha: 0.32),
              blurRadius: 22,
              spreadRadius: 1.5,
            ),
          ],
        ),
        child: CustomPaint(
          painter: _BallSeamPainter(accent: accent.withValues(alpha: 0.78)),
        ),
      ),
    );
  }
}

class _BallSeamPainter extends CustomPainter {
  const _BallSeamPainter({required this.accent});

  final Color accent;

  @override
  void paint(Canvas canvas, Size size) {
    final seamPaint = Paint()
      ..color = accent
      ..style = PaintingStyle.stroke
      ..strokeWidth = size.shortestSide * 0.09
      ..strokeCap = StrokeCap.round;

    final seam = Path()
      ..moveTo(size.width * 0.28, size.height * 0.22)
      ..quadraticBezierTo(
        size.width * 0.18,
        size.height * 0.50,
        size.width * 0.30,
        size.height * 0.78,
      );
    final seamMirror = Path()
      ..moveTo(size.width * 0.72, size.height * 0.22)
      ..quadraticBezierTo(
        size.width * 0.82,
        size.height * 0.50,
        size.width * 0.70,
        size.height * 0.78,
      );

    canvas.drawPath(seam, seamPaint);
    canvas.drawPath(seamMirror, seamPaint);
  }

  @override
  bool shouldRepaint(covariant _BallSeamPainter oldDelegate) {
    return oldDelegate.accent != accent;
  }
}

class _PitchFieldPainter extends CustomPainter {
  _PitchFieldPainter({
    required this.round,
    required this.motion,
    required this.progress,
    required this.accent,
    required this.outcomeColor,
    required this.promptVisible,
    required this.answered,
    required this.selectedIndex,
  });

  final TrainingRound round;
  final PitchMotionSpec motion;
  final double progress;
  final Color accent;
  final Color outcomeColor;
  final bool promptVisible;
  final bool answered;
  final int? selectedIndex;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;

    final backgroundPaint = Paint()
      ..shader = LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [
          const Color(0xFF091524),
          const Color(0xFF0B1C32),
          const Color(0xFF08111D),
        ],
      ).createShader(rect);
    canvas.drawRRect(
      RRect.fromRectAndRadius(rect, Radius.circular(size.shortestSide * 0.08)),
      backgroundPaint,
    );

    _drawPerspectiveLanes(canvas, size, accent);
    _drawZone(canvas, size, accent, outcomeColor);
    _drawMound(canvas, size, accent);
    _drawPlate(canvas, size, accent);
    _drawTrail(canvas, size, accent, outcomeColor);
    _drawTargetGlow(canvas, size, outcomeColor);

    if (!promptVisible) {
      _drawReleaseHint(canvas, size, accent);
    }

    if (answered && selectedIndex != null) {
      _drawOutcomeAccent(canvas, size, outcomeColor);
    }
  }

  void _drawPerspectiveLanes(Canvas canvas, Size size, Color accent) {
    final lanePaint = Paint()
      ..color = accent.withValues(alpha: 0.12)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;

    final plate = motion.samplePoint(size, 1);
    final horizonY = size.height * 0.14;
    for (var i = -2; i <= 2; i += 1) {
      final bias = i * size.width * 0.10;
      final path = Path()
        ..moveTo(size.width * 0.50 + bias * 0.40, horizonY)
        ..quadraticBezierTo(
          size.width * 0.52 + bias * 0.18,
          size.height * 0.46,
          plate.dx + bias * 0.08,
          plate.dy - size.height * 0.03,
        );
      canvas.drawPath(path, lanePaint);
    }
  }

  void _drawZone(Canvas canvas, Size size, Color accent, Color outcomeColor) {
    final zoneRect = Rect.fromCenter(
      center: Offset(size.width * 0.50, size.height * 0.70),
      width: size.width * 0.23,
      height: size.height * 0.28,
    );
    final zonePaint = Paint()
      ..color = Colors.white.withValues(alpha: 0.04)
      ..style = PaintingStyle.fill;
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        zoneRect,
        Radius.circular(size.shortestSide * 0.02),
      ),
      zonePaint,
    );

    final borderPaint = Paint()
      ..color = Colors.white.withValues(alpha: 0.18)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.4;
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        zoneRect,
        Radius.circular(size.shortestSide * 0.02),
      ),
      borderPaint,
    );

    final highlightPaint = Paint()
      ..color = promptVisible ? outcomeColor.withValues(alpha: 0.18) : accent.withValues(alpha: 0.12)
      ..style = PaintingStyle.fill;
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        zoneRect.deflate(size.shortestSide * 0.01),
        Radius.circular(size.shortestSide * 0.018),
      ),
      highlightPaint,
    );

    final linePaint = Paint()
      ..color = Colors.white.withValues(alpha: 0.10)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    canvas.drawLine(
      Offset(zoneRect.center.dx, zoneRect.top),
      Offset(zoneRect.center.dx, zoneRect.bottom),
      linePaint,
    );
    canvas.drawLine(
      Offset(zoneRect.left, zoneRect.center.dy),
      Offset(zoneRect.right, zoneRect.center.dy),
      linePaint,
    );
  }

  void _drawMound(Canvas canvas, Size size, Color accent) {
    final moundRect = Rect.fromCenter(
      center: Offset(size.width * 0.50, size.height * 0.15),
      width: size.width * 0.18,
      height: size.height * 0.06,
    );
    canvas.drawOval(
      moundRect,
      Paint()..color = accent.withValues(alpha: 0.10),
    );
    canvas.drawOval(
      moundRect.deflate(4),
      Paint()
        ..color = Colors.white.withValues(alpha: 0.06)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1,
    );
  }

  void _drawPlate(Canvas canvas, Size size, Color accent) {
    final plate = motion.samplePoint(size, 1);
    final plateWidth = size.width * 0.08;
    final plateHeight = size.height * 0.035;
    final plateRect = Rect.fromCenter(
      center: Offset(plate.dx, size.height * 0.88),
      width: plateWidth,
      height: plateHeight,
    );
    final platePath = Path()
      ..moveTo(plateRect.left, plateRect.top + plateRect.height * 0.25)
      ..lineTo(plateRect.left + plateRect.width * 0.18, plateRect.bottom)
      ..lineTo(plateRect.right - plateRect.width * 0.18, plateRect.bottom)
      ..lineTo(plateRect.right, plateRect.top + plateRect.height * 0.25)
      ..lineTo(plateRect.center.dx, plateRect.top)
      ..close();

    canvas.drawShadow(platePath, Colors.black.withValues(alpha: 0.42), 8, false);
    canvas.drawPath(
      platePath,
      Paint()
        ..color = Colors.white.withValues(alpha: 0.20)
        ..style = PaintingStyle.fill,
    );
    canvas.drawPath(
      platePath,
      Paint()
        ..color = accent.withValues(alpha: 0.18)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.2,
    );
  }

  void _drawTrail(Canvas canvas, Size size, Color accent, Color outcomeColor) {
    final trail = Path();
    final sampleCount = math.max(10, (progress * 24).round());
    for (var i = 0; i <= sampleCount; i += 1) {
      final t = progress * (i / sampleCount);
      final point = motion.samplePoint(size, t);
      if (i == 0) {
        trail.moveTo(point.dx, point.dy);
      } else {
        trail.lineTo(point.dx, point.dy);
      }
    }

    final trailPaint = Paint()
      ..color = outcomeColor.withValues(alpha: motion.trailOpacity(progress))
      ..style = PaintingStyle.stroke
      ..strokeWidth = lerpDouble(5, 2, progress.clamp(0.0, 1.0))!
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    canvas.drawPath(trail, trailPaint);

    final glowPaint = Paint()
      ..color = accent.withValues(alpha: 0.10)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 10
      ..strokeCap = StrokeCap.round;
    canvas.drawPath(trail, glowPaint);
  }

  void _drawTargetGlow(Canvas canvas, Size size, Color outcomeColor) {
    final center = Offset(size.width * 0.50, size.height * 0.70);
    final glowRect = Rect.fromCircle(center: center, radius: size.shortestSide * 0.18);
    canvas.drawOval(
      glowRect,
      Paint()
        ..shader = RadialGradient(
          colors: [
            outcomeColor.withValues(alpha: promptVisible ? 0.16 : 0.08),
            Colors.transparent,
          ],
        ).createShader(glowRect),
    );
  }

  void _drawReleaseHint(Canvas canvas, Size size, Color accent) {
    final release = motion.samplePoint(size, 0);
    final hintRect = Rect.fromCenter(
      center: Offset(release.dx, release.dy - size.height * 0.05),
      width: size.width * 0.22,
      height: size.height * 0.06,
    );
    final hintPaint = Paint()
      ..shader = LinearGradient(
        colors: [
          accent.withValues(alpha: 0.18),
          Colors.transparent,
        ],
      ).createShader(hintRect);
    canvas.drawRRect(
      RRect.fromRectAndRadius(hintRect, Radius.circular(size.shortestSide * 0.04)),
      hintPaint,
    );
  }

  void _drawOutcomeAccent(Canvas canvas, Size size, Color outcomeColor) {
    final center = motion.samplePoint(size, 1);
    final ringRect = Rect.fromCircle(
      center: Offset(center.dx, size.height * 0.88),
      radius: size.shortestSide * 0.08,
    );
    canvas.drawOval(
      ringRect,
      Paint()
        ..color = outcomeColor.withValues(alpha: 0.10)
        ..style = PaintingStyle.fill,
    );
    canvas.drawOval(
      ringRect,
      Paint()
        ..color = outcomeColor.withValues(alpha: 0.32)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.4,
    );
  }

  @override
  bool shouldRepaint(covariant _PitchFieldPainter oldDelegate) {
    return oldDelegate.round.id != round.id ||
        oldDelegate.progress != progress ||
        oldDelegate.promptVisible != promptVisible ||
        oldDelegate.answered != answered ||
        oldDelegate.selectedIndex != selectedIndex ||
        oldDelegate.outcomeColor != outcomeColor;
  }
}

class _SceneStatPill extends StatelessWidget {
  const _SceneStatPill({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        color: Colors.white.withValues(alpha: 0.08),
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
          const SizedBox(height: 2),
          Text(
            value,
            style: Theme.of(context).textTheme.labelLarge?.copyWith(
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }
}

Color _accentForMode(TrainingMode mode) {
  return switch (mode) {
    TrainingMode.pitchType => const Color(0xFF62E6FF),
    TrainingMode.strikeZone => const Color(0xFF84F58E),
    TrainingMode.swingDecision => const Color(0xFFFFCF72),
  };
}

IconData _iconForMode(TrainingMode mode) {
  return switch (mode) {
    TrainingMode.pitchType => Icons.sports_baseball_rounded,
    TrainingMode.strikeZone => Icons.center_focus_strong_rounded,
    TrainingMode.swingDecision => Icons.bolt_rounded,
  };
}

Offset _scale(Offset point, Size size) {
  return Offset(point.dx * size.width, point.dy * size.height);
}

Offset _clamped(double dx, double dy) {
  return Offset(
    dx.clamp(0.08, 0.92).toDouble(),
    dy.clamp(0.06, 0.95).toDouble(),
  );
}

Offset _cubicBezier(Offset p0, Offset p1, Offset p2, Offset p3, double t) {
  final oneMinusT = 1 - t;
  final oneMinusTSquared = oneMinusT * oneMinusT;
  final tSquared = t * t;
  final a = oneMinusTSquared * oneMinusT;
  final b = 3 * oneMinusTSquared * t;
  final c = 3 * oneMinusT * tSquared;
  final d = tSquared * t;
  return Offset(
    a * p0.dx + b * p1.dx + c * p2.dx + d * p3.dx,
    a * p0.dy + b * p1.dy + c * p2.dy + d * p3.dy,
  );
}
