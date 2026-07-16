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
3. Treat `.like-icon-active` as a DOM success signal only when the action target has first been joined to one trusted Platform Identity.
4. The clicked detail subtree exposed no trusted identity attribute names. Production code must join the action target to separately captured identity evidence and must never infer the candidate from name, text, or card position.
5. Keep zero-match and multi-match cases non-writing: `identity_incomplete` and `identity_conflict` respectively.

## Primary source

The disposable prototype and its verdict are preserved on branch `prototype/passive-favorite-diagnostic`:

- `e342312` — passive cross-frame observation prototype
- `59c03b8` — favorite-management confirmation
