# BOSS Native Favorite live validation — 2026-07-16

## Outcome

Manual Native Favorite was validated end to end on the BOSS recruiter recommendation experience without external browser takeover.

- Top-level route: `/web/chat/recommend`
- Candidate-detail frame route: `/web/frame/recommend/`
- Manual action chain: `.resume-item-detail` → `.like-icon-and-text` → `.btn-text`
- Observed post-action signal: `.like-icon` gained `.like-icon-active` about 245 ms after the trusted manual click.
- Platform confirmation: the same test candidate appeared under BOSS **互动 → 收藏牛人**.

The validation recorded no candidate name, resume text, identity value, Cookie, Token, request header, or request body.

## Technical decisions

1. Do not use Codex/Playwright/CDP tab takeover for BOSS. It caused page refresh, redirect, or exit during validation.
2. Run the platform adapter inside the existing Manifest V3 extension and include the candidate-detail frame.
3. Treat `.like-icon-active` only as a DOM post-action/active signal after the action target has been joined to one trusted Platform Identity. It is not final Native Favorite success; the same identity must still be verified in the favorite-management experience.
4. The clicked detail subtree exposed no trusted identity attribute names. Production code must join the action target to separately captured identity evidence and must never infer the candidate from name, text, or card position.
5. Keep zero-match and multi-match cases non-writing: `identity_incomplete` and `identity_conflict` respectively.

## Identity-to-detail join validation — 2026-07-17

A follow-up read-only prototype validated the production navigation seam without exposing identity values:

- The clicked candidate card carried the exact attribute name `data-geekid`.
- Exactly one salted identity digest was associated with the trusted manual card click.
- Candidate list and detail share `/web/frame/recommend/`; frame path alone is therefore not identity evidence.
- The click was followed by two mutations inside the detail experience.
- About 900 ms later, `.resume-item-detail` existed with `.like-icon-and-text` available.
- The detail subtree still exposed no direct trusted Platform Identity.

The validated join is causal: production must uniquely match an explicit typed `data-geekid` identity, click that exact card, and require a new detail root or a newly generated favorite control after a detail mutation before attempting a Native Favorite. An unrelated mutation around the previous control is insufficient. Zero or multiple matches, no detail generation change, or an intervening trusted selection fail closed. Name, candidate text, and list position remain prohibited identity evidence. A local `.like-icon-active` signal remains `unknown` until the same Platform Identity is verified in the favorite-management experience.

## Favorite-management identity verification — 2026-07-17

The same test candidate was verified read-only in BOSS **互动 → 收藏牛人**:

- Top-level route: `/web/chat/interaction`.
- Candidate list frame: `/web/frame/recommend/`.
- The visible list exposed 26 distinct `data-geekid` identities.
- The source candidate's salted identity digest matched exactly once under the same `data-geekid` attribute type.
- The match required no name, candidate text, `data-geek` value, or list position.

This validates the final classification seam. One exact typed match confirms presence in the Native Favorite pool: a task that attempted the write becomes `success`, while a task that skipped the write because the page was already active becomes `already_favorited`. Multiple matches are `identity_conflict`. Zero visible matches remain `unknown` because the management list may be partially loaded; the verifier must not infer absence, navigate, scroll, or click.

## Primary source

The disposable prototype and its verdict are preserved on branch `prototype/passive-favorite-diagnostic`:

- `e342312` — passive cross-frame observation prototype
- `59c03b8` — favorite-management confirmation
- `928c763` — causal identity-to-detail join verdict
- `85707f1` — favorite-management exact identity-match verdict
