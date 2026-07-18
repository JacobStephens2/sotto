# ADR-003: Streaming chunk-ahead-of-playhead synthesis in one foreground media service

Status: accepted
Date: 2026-06-12

## Decision

Synthesis streams just ahead of the playhead: the engine synthesizes chunk n+k
while the user listens to chunk n, pausing when ~3 minutes of audio are buffered
ahead and resuming as the playhead approaches the frontier. Both the ExoPlayer
and the NarrationEngine live in one `MediaSessionService` whose foreground type
is `mediaPlayback`. Synthesis without active listening (queued items, user not
playing) runs as expedited WorkManager work that checkpoints per chunk.

## Context

The council research's strongest argument against on-device synthesis was the
batch framing: a 40-minute background job is exactly what Doze kills and Play
policy scrutinizes. Streaming dissolves that framing. While the user listens,
the work rides inside the one background shape Android explicitly blesses - an
active foreground media-playback service. The 38,000-word document that takes
hours to synthesize in batch becomes seconds-to-first-audio and is mostly
synthesized by the time the listener reaches the end.

It is also simply the better product: the sotto web app added
preview-while-narrating for the same reason; this design makes the preview the
primary experience.

When the user is *not* listening, we deliberately do not fight Doze: WorkManager
runs when the OS allows, every chunk is a durable checkpoint (data-model
invariant 1), and resume is free. Synthesis throughput for unattended jobs is
best-effort by design.

## Consequences

- The playhead can catch the frontier on slow/throttled devices → the playhead
  governor pauses playback with a "catching up" state (PRD edge case). RTF ≥
  1.3x (SPIKE-001 target) makes this rare.
- Notification UX must combine playback controls and synthesis progress in one
  notification - one service, one notification, no juggling.
- Battery cost concentrates during listening sessions, where the user expects
  drain, rather than in mysterious background heat.
- Rules out "share and it's instantly fully ready later" expectations for
  unattended jobs; the library communicates partial progress honestly instead.
