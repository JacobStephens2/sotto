# Design System / UI Style Guide - sotto-android

## Stance

Material 3, dynamic color, native Android conventions throughout. The app does
not imitate the sotto website's look - shared identity is the name, the
boundary story, and the voices, not pixels (20-platform-strategy.md). Where the
web app is deliberately plain, this app is deliberately *stock*: the design
system is "well-made default Android," which is both the honest scope for a
solo project and the right register for a trust-centered utility.

## Foundations

- **Color:** Material 3 dynamic color from the user's wallpaper; static
  fallback seed `#002A4F` (the sotto brand navy, the one visual continuity
  with the web app and favicon). Full dark-mode support; AMOLED-friendly pure
  black is a settings toggle later, not v1.
- **Typography:** default Material 3 type scale, system font. Source-text view
  uses the platform monospace at 14sp minimum.
- **Spacing:** 4dp grid; standard Material component padding; no custom values
  without a reason written next to them.
- **Iconography:** Material Symbols. App icon: speaker-with-soundwaves motif on
  the navy - visually related to the web favicon, redrawn for adaptive-icon
  masks.

## Components (v1 inventory, all stock M3)

TopAppBar, LargeFloatingActionButton (paste entry), ListItem (library),
LinearProgressIndicator (narration progress), Slider (seek, speed), AlertDialog
(delete/stop confirm), ModalBottomSheet (voice picker with inline previews),
SnackBar (errors), Switch/RadioButton (settings). Custom composables limited
to: the player transport cluster and the "catching up" frontier indicator.

## The player screen

The one screen worth real design effort (it's the product). Big play/pause,
15-second skip pair (the web app's `« 15s / 15s »` convention), elapsed/total,
speed chip, sleep-timer chip, chunk-progress line during narration. Controls
mirror the MediaSession notification one-for-one - no capability that exists in
one place and not the other.

## Accessibility (release criteria, not aspirations)

- Every transport control has a contentDescription; TalkBack order follows
  visual order; the progress line announces "narrating, n of N chunks."
- Touch targets ≥ 48dp; text respects system font scale to 200% without
  truncation; contrast per M3 defaults (don't override token pairs).
- Playback state changes are announced via MediaSession metadata, not toasts.

## Writing in the UI

Follows the server's wording rule: **narrating/oration** in user-facing text,
**synthesized/Kokoro-82M** in the About screen's provenance section. Sentence
case everywhere, no exclamation marks, no "please." Empty states say what to do
("Share text to sotto from any app, or paste it here."), errors say what
happened and what survives ("Storage full - narration stopped after chunk 41.
Everything narrated so far is saved.").
