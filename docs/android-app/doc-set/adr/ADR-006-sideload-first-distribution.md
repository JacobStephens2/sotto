# ADR-006: Sideload-first distribution via GitHub releases; Play deferred

Status: accepted
Date: 2026-06-12

## Decision

1.0 ships as a signed APK attached to a GitHub release on the public
`sotto-android` repo. Google Play is a separate post-1.0 decision; F-Droid
submission is considered alongside it.

## Context

This is the proven low-friction path from MacroTracker (GitHub-release APK +
signing convention) and Quorum (sideload-only). The known Play costs - the
12-tester/14-day internal-testing requirement on a personal account (learned on
Creighton), developer verification (legal identity, gating since March 2026),
listing assets, data-safety forms - buy nothing for an app whose first users are
me and readers of the repo.

F-Droid deserves real consideration at or after 1.0: a FOSS app with no network
permission and an openly licensed bundled model is exactly their catalog, their
build/reproducibility requirements are the main cost, and their audience is
precisely the privacy-conscious target user from the concept brief.

If Play happens later, the compliance work is already enumerated
(32-compliance-checklist.md) and is unusually light for this app: no data
collected, no accounts (so no account-deletion mechanism needed), AI disclosure
already in the About screen.

## Consequences

- Users must enable unknown-source installs; the README documents this without
  apologizing for it.
- No staged rollouts or Play vitals; the device matrix in 30-testing-plan.md is
  the safety net.
- Signing key management is ours alone (31-release-cicd-plan.md) - generate a
  dedicated keystore with a strong password (the MacroTracker weak-keystore
  caveat is a known mistake not to repeat), store it outside the repo, document
  recovery.
