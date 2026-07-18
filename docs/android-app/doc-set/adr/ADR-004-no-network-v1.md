# ADR-004: No INTERNET permission in the `local` flavor; the manifest is the privacy claim

Status: accepted (scoped to the `local` flavor by ADR-007)
Date: 2026-06-12

## Decision

The `local` flavor's merged AndroidManifest does not declare
`android.permission.INTERNET` (nor `ACCESS_NETWORK_STATE`). No network library
appears in its dependency graph. CI fails the build if either permission
appears in the merged manifest (31-release-cicd-plan.md). The `local` artifact
is the flagship release and carries the public claim; the `sync` flavor
(ADR-007) holds INTERNET and makes its own, weaker-but-honest claim.

## Context

The sotto server's boundary story rests on trusting the operator. An app whose
*manifest* lacks the INTERNET permission makes the stronger claim mechanically
verifiable by anyone: `aapt dump permissions sotto.apk` - the OS itself will
refuse the app a socket. This converts a privacy promise into a falsifiable
property, which is the most distinctive line in the product's README and the
cleanest possible translation of the seven-boundary checklist
(secret isolation → no secret exists; bounded scope → no network exists).

The cost is real and accepted: no crash reporting, no analytics, no update
checks, no URL-sharing input, and the model cannot be downloaded at first run -
it must ship in the APK (ADR-005).

## Consequences

- Crash diagnostics are local only (a user-initiated "export logs" file via SAF
  is permissible - the user moves it, the app doesn't send it).
- Update discovery happens outside the app (GitHub releases / F-Droid client).
- Server sync is a separate build flavor (ADR-007) whose README plainly states
  the difference; the no-network flavor remains the flagship artifact.
- Merged-manifest vigilance: transitive dependencies can inject INTERNET; the
  CI check exists because of exactly that failure mode.
