# Constitution - sotto-android

Executable constraints. Every change - human- or agent-written - must satisfy
these. They are checked, not aspirational: each names its enforcement.

## Boundaries (the product's seven, translated)

1. **No account required.** Narration never depends on login or network. The
   `sync` flavor must behave identically to `local` until an account is
   explicitly connected. *Enforced by:* engine has no reference to sync code
   (compile-time, package rules in 40-code-style.md).
2. **No secret exists.** The app holds no API keys. The only credential ever
   stored is the user's own sync token, in Android Keystore-backed encrypted
   storage, sent only to the server the user named. *Enforced by:* code review
   + dependency allowlist.
3. **Bounded scope.** `local` flavor: no INTERNET/ACCESS_NETWORK_STATE in the
   merged manifest. `sync` flavor: INTERNET only, one HTTP client, connects
   only to the user-configured sotto server. *Enforced by:* CI manifest guards
   (31-release-cicd-plan.md) - a failing build, not a review comment.
4. **Not delegated.** The app produces audio and stops. It never posts,
   publishes, emails, or shares on its own; export and upload are explicit user
   actions each time. No background sync without a user-visible setting that
   defaults off. *Enforced by:* PRD review gate on any feature touching
   sharing/upload.
5. **Traceability.** Every oration lifecycle event writes one local job-log
   line; sync actions log what went where. The log is viewable in-app and never
   transmitted. *Enforced by:* JobLogEntry coverage assertions in engine tests.
6. **Provenance honesty.** The About screen names Kokoro-82M, its Apache-2.0
   license, and its documented training data; calls the voices synthetic; in
   `local`, states the no-network property next to its verification command.
   *Enforced by:* release checklist item + a UI test asserting the screen's
   key strings.
7. **The user's material is the user's.** Orations, source text, and the log
   are exportable via SAF at any time; deleting is real deletion. *Enforced by:*
   PRD acceptance S3/S5.

## Engineering invariants

8. Chunk-boundary durability: progress persists only after fsync; resume is
   byte-identical (tested, 30-testing-plan.md).
9. The text pipeline matches the server's reference implementation via the
   shared vector file; vector drift fails CI.
10. One synthesis worker, ever.
11. `engine/` imports no UI, no Android services, no network (compile-time).
12. Performance numbers in any README/release note come from measurements
    recorded in `_state.md`, never from estimates.

## Process rules

13. Architecturally significant decisions get an ADR before merge.
14. Docs in this set version with the code: a PR that changes behavior a doc
    describes updates the doc in the same PR.
15. No commit trailers attributing authorship to tools.
