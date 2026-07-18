# ADR-002: On-device synthesis with sherpa-onnx running Kokoro-82M int8

Status: accepted (confirmation gated on SPIKE-001 measurements)
Date: 2026-06-12

## Decision

Speech is synthesized on the device by Kokoro-82M, int8-quantized ONNX weights
(onnx-community/Kokoro-82M-v1.0-ONNX lineage), executed by sherpa-onnx through
its Kotlin/JNI bindings. Phonemization is sherpa-onnx's bundled espeak-ng. The
same 7 curated voices as the sotto server (`af_heart` default).

## Context

- **Provenance is the product.** Kokoro-82M is Apache-2.0 with documented
  public-domain/permissively-licensed training audio - the same model the sotto
  server chose for Magnifica-Humanitas alignment. On-device, the claim
  strengthens from "no audio leaves the server" to "no audio leaves the device."
- **Feasibility is precedented, not assumed.** The council research surfaced
  puff-dayo/Kokoro-82M-Android (int8 Kokoro running on Android) and the official
  quantized weights (~80-170 MB int8 vs 311 MB fp32). SPIKE-001 measures RTF,
  battery, and thermals on our own floor device before Phase 1 begins.
- **Alternatives rejected:** Android's built-in `TextToSpeech` (Gemini's
  suggestion in the council) has undocumented provenance and per-device voice
  quality - it forfeits the entire thesis. Cloud TTS forfeits it twice. Larger
  open models don't fit phone thermals.
- sherpa-onnx over raw onnxruntime: it packages the full Kokoro pipeline
  (phonemizer, voice embeddings, session config) behind a maintained Kotlin API;
  raw ORT would mean reimplementing misaki/espeak-ng integration ourselves.

## Consequences

- ~100-200 MB of model assets ship in the APK (ADR-005).
- English-first; other languages arrive only as Kokoro/sherpa support them.
- Synthesis speed is device-bound → the streaming design (ADR-003) is mandatory,
  not optional.
- If SPIKE-001 fails its gate (RTF < 1.0x sustained), this ADR is reopened -
  candidates: smaller distill, batch pre-synthesis mode, or shelving the product.
