---
version: alpha
name: Batter’s Eye
description: Dark baseball analytics UI inspired by PitchLab, with Duolingo-like coach nudges and premium discipline.
colors:
  bg-950: "#06111F"
  bg-900: "#07111F"
  bg-850: "#0B1730"
  surface-800: "#10233C"
  surface-700: "#162A4A"
  text-primary: "#F5F8FF"
  text-secondary: "rgba(255,255,255,0.72)"
  text-muted: "rgba(255,255,255,0.52)"
  border-subtle: "rgba(255,255,255,0.08)"
  accent-cyan: "#62E6FF"
  accent-mint: "#84F58E"
  accent-amber: "#FFCF72"
  accent-rose: "#FF6B7A"
  on-accent: "#06111F"
typography:
  h1:
    fontFamily: Roboto
    fontSize: 32px
    fontWeight: 800
    lineHeight: 1.25
    letterSpacing: "-0.03em"
  h2:
    fontFamily: Roboto
    fontSize: 24px
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.02em"
  body:
    fontFamily: Roboto
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: Roboto
    fontSize: 12px
    fontWeight: 600
    lineHeight: 1.2
layout:
  screen-padding: 20px
  section-gap: 16px
  card-gap: 12px
  card-padding: 18px
  radius-card: 24px
  radius-button: 18px
  radius-pill: 999px
elevation:
  card: none
  focus-ring: "0 0 0 1px rgba(255,255,255,0.12)"
shapes:
  cards: rounded rectangles with subtle borders
  buttons: rounded rectangles with short labels
  chips: pills with compact values
components:
  primary-button:
    backgroundColor: "{colors.accent-cyan}"
    textColor: "{colors.on-accent}"
    rounded: "{layout.radius-button}"
    padding: 14px
  secondary-button:
    backgroundColor: "{colors.surface-800}"
    textColor: "{colors.text-primary}"
    rounded: "{layout.radius-button}"
    padding: 14px
  card:
    backgroundColor: "{colors.surface-800}"
    textColor: "{colors.text-primary}"
    rounded: "{layout.radius-card}"
    padding: "{layout.card-padding}"
do-and-dont:
  do:
    - Keep one strong accent per screen.
    - Use generous spacing, clear hierarchy, and data-first cards.
    - Make feedback short, direct, and coach-like.
  dont:
    - Avoid heavy glassmorphism and neon overload.
    - Avoid dense text blocks and tight spacing.
    - Avoid relying on color alone for status.
---

## Overview

Batter’s Eye should feel like a daily baseball lab: short, useful, and encouraging.
The UI is dark, athletic, and premium, with PitchLab-like precision, clean analytics cards, and a focus on zone/trajectory reading rather than arcade noise.

## Colors

- **bg-950 / bg-900**: main shell background.
- **bg-850 / surface-800 / surface-700**: card layers and nested surfaces.
- **accent-cyan**: primary action and core metrics.
- **accent-mint**: success, correct answers, progress.
- **accent-amber**: insight, caution, recommended hints.
- **accent-rose**: wrong answer / miss state.

## Typography

Use a clean system sans-serif. Keep headings bold and short. Body copy should stay readable and calm. Korean copy should lead; English can appear in labels and mode names.

## Layout & Spacing

Use an 8pt rhythm. Screen padding should stay around 20px. Cards need enough breathing room for the app to feel premium, especially on the onboarding and dashboard screens.

## Elevation & Depth

Prefer flat surfaces with subtle borders instead of heavy shadows. Use gradients only for hero cards or progress accents.

## Shapes

Cards should be rounded at 24px, buttons at 18px, chips fully pill-shaped. Avoid sharp corners unless a component is intentionally informational.

## Components

- **Primary button**: one main action per screen.
- **Secondary button**: for low-emphasis choices like sign out or back.
- **Metric pill**: compact summary for level, accuracy, reaction time.
- **Mode card**: stacked content with icon, title, short subtitle, and one action.

## Do’s and Don’ts

### Do
- Keep the onboarding flow short.
- Show progress and next action immediately.
- Reuse the same accent language across auth, profile, placement, and dashboard.

### Don’t
- Don’t overuse gradients.
- Don’t crowd the screen with too many cards.
- Don’t rely on tiny text or low-contrast gray.
- Don’t make the app feel like a generic habit tracker.
