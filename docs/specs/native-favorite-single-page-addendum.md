# Native Favorite Single-Page Two-Phase Addendum

This addendum supersedes any simultaneous recommendation-page and Favorite Talent page requirement in the original single-batch specification.

- BOSS may allow only one active business page. Production must not require recommendation and Favorite Talent pages simultaneously.
- Phase 1 runs only in the locked Source Page Context. An exact source detail control becoming active records `verification_pending`; it is not final Native Favorite success.
- After Phase 1 finishes, the user navigates the same BOSS page to `Interaction -> Favorite Talent` and explicitly starts Phase 2.
- The desktop database is the durable source of truth for the phase and task counts. Phase 2 is unavailable until every permitted Phase 1 action has finished.
- Phase 2 must run in the same browser tab recorded by Phase 1. Navigating that tab is allowed; opening another BOSS tab is not a substitute.
- Phase 2 is read-only. It claims only `verification_pending` tasks and finalizes `success` or `already_favorited` only after an exact Platform Identity match in the selected management experience.
- A zero-match or otherwise inconclusive management scan returns the task to `verification_pending` and pauses. Re-running Phase 2 never repeats the source favorite click.
- Tasks beyond the per-batch action limit are preserved as `deferred`; they do not block verification of actions already attempted.
- The batch state distinguishes source `pending/running`, `awaiting_verification/verifying`, `deferred`, and final terminal outcomes.
