# Release / CI/CD Plan

## Repo and branching

Public GitHub repo `sotto-android` (license per the repo-licensing
conventions for apps - decide at repo creation, before first push). Trunk-based:
`master` is always releasable; short-lived branches for anything risky; no
develop branch ceremony for a solo project.

## CI (GitHub Actions)

`ci.yml` on every push/PR:
1. ktlint + Android lint
2. JVM unit tests (pipeline vectors, state machine, estimator)
3. Instrumented tests on emulator (x86_64 debug variant, stub model)
4. **Manifest guard:** build, then fail if `aapt dump permissions` on the merged
   output contains INTERNET or ACCESS_NETWORK_STATE (ADR-004's enforcement)
5. Assemble debug APK as a workflow artifact

`release.yml` on tag `v*`:
1. Everything in ci.yml
2. Assemble signed arm64 release APK (model assets included)
3. Generate checksums; attach APK + SHA-256 to a GitHub release
4. Release notes template includes: version, the re-measured RTF/battery
   numbers (30-testing-plan.md), and the `aapt dump permissions` output -
   publishing the no-network proof with every release

Build hosts: GitHub-hosted runners. Local builds work on the VPS only if the
disk situation allows (the Cascade build-output-on-volume pattern applies);
develop primarily against a local machine or the runner artifacts.

## Signing

- Dedicated keystore for this app, generated fresh with a strong password -
  explicitly not repeating the MacroTracker weak-keystore-password mistake.
- Keystore lives outside any repo; CI receives it as base64 GitHub secrets
  (`KEYSTORE_B64`, `KEYSTORE_PASS`, `KEY_ALIAS`, `KEY_PASS`).
- Recovery documented privately (password manager + offline copy). Losing this
  key forfeits upgrade continuity for sideload users - treat accordingly.

## Versioning

Semver tags. `versionCode` = monotonic integer; `versionName` = tag.
Data migrations: Room schema versions reviewed at every release; an upgrade
install over the previous release is part of release criteria.

## Distribution

1. GitHub release (primary, from 1.0 - ADR-006)
2. F-Droid: evaluate after 1.0 (reproducible-build work is the cost)
3. Play: separate decision post-1.0; if taken, `release.yml` grows an AAB +
   Play Asset Delivery lane and the 32-compliance-checklist items activate

## Rollback

Sideload rollback = reinstall previous APK (allow `versionCode` downgrade via
uninstall/reinstall; Room migrations are forward-only, so document that
downgrade may need a data reset). Keep the last three releases' APKs attached
to GitHub releases permanently.
