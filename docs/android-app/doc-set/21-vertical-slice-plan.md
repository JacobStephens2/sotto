# Vertical Slice Plan

The smallest complete, production-quality path through the real architecture.
When this slice works, the architecture is proven; everything after it is
surface area. This is Roadmap Phase 2; SPIKE-001 and the Phase 1 engine are its
prerequisites.

## The slice

**Share selected text from Chrome → hear it narrated with the screen off →
find it in the library tomorrow.**

Expanded:

1. User selects two paragraphs in any app → Share → "sotto".
2. Confirm screen: derived title shown, voice = af_heart, estimated time, one
   Narrate button. (No name editing, no voice previews - Phase 3.)
3. NarrationService starts foreground; first audio within 10 s; notification
   shows play/pause + chunk progress.
4. User locks the screen; playback and synthesis continue; headphone pause works.
5. User force-stops the app mid-narration, reopens: oration resumes from the
   last completed chunk, playhead restored.
6. Next day: library list shows the entry with title, length, COMPLETE status;
   tapping plays from the saved position.

## What the slice must exercise (the point of the exercise)

- Share-intent entry path (the primary product entry, so it goes first)
- The ported text pipeline against real-world messy text
- sherpa-onnx synthesis on-device in the service, not in a test harness
- Growing-file playback in ExoPlayer + the playhead governor
- One-notification MediaSession UX
- Room persistence, chunk-boundary durability, resume after process death
- CI: every merge builds a signed debug APK; the release pipeline runs end to
  end at least once (31-release-cicd-plan.md)

## Explicitly out of slice

Rename, delete, source-text view, voice picker UI, speed control, sleep timer,
queueing of multiple shares, About screen, estimator calibration (a hardcoded
rate is fine), paste-box entry, file-open entry.

## Exit gate

I use the slice build daily for one week of real walk-listening. Defects that
interrupt audio or lose an oration block Phase 3; cosmetic issues get tickets in
tasks.md and don't.
