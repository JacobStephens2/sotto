# ADR-007: Two build flavors - `local` (no network, flagship claim) and `sync` (opt-in server account)

Status: accepted
Date: 2026-06-12

## Decision

The app builds in two product flavors from one codebase:

- **`local`** - the flagship artifact. No INTERNET permission (ADR-004 applies
  in full). The public README's headline claim belongs to this flavor.
- **`sync`** - everything in `local`, plus opt-in connection to a sotto server
  account: browse the server library, download entries to the device, upload
  local orations to the account, so the same library is usable from the phone
  and a desktop browser. Holds INTERNET; all network code lives in the
  `sync` source set and is dead code nowhere - it simply doesn't exist in
  `local` builds.

Both artifacts are published with every release, named unambiguously
(`sotto-local-vX.Y.Z.apk`, `sotto-sync-vX.Y.Z.apk`).

## Context

The owner's primary personal requirement (2026-06-12) is working with one
library from both Android and the desktop browser - that requires the network.
The product's most distinctive public claim - "the manifest proves nothing
leaves the device" - requires the absence of the network. One app cannot make
both moves; two flavors can, honestly, because the claim attaches to the
artifact you install, and each artifact's manifest tells its own truth.

Synthesis remains 100% on-device in both flavors. The sync flavor talks only to
the sotto server you name; it never adds hosted TTS, telemetry, or any third
party. Its honest claim: "narrates on-device; syncs your library with your own
server when - and only when - you connect an account."

## Consequences

- The CI manifest guard (ADR-004) runs against the `local` flavor; the `sync`
  flavor gets its own guard: INTERNET allowed, any *other* added permission
  fails the build, and the dependency graph is allowlisted (one HTTP client).
- The API Contract document (12-api-contract.md) is in scope and the sotto
  server grows a small token-auth API (server-side work, tracked in tasks.md).
- Engine code stays flavor-agnostic; sync is a peripheral feature of the
  library, never a dependency of narration. The app must behave identically to
  `local` until an account is connected.
- Two artifacts to test and release; accepted - the flavor split is exactly the
  axis the test matrix already cares about.
