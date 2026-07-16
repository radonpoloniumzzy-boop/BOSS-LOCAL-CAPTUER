# Separate platform-action identity from legacy candidate deduplication

The first Native Favorite milestone will preserve the existing candidate deduplication behavior to avoid destabilizing historical data, while requiring trusted Platform Identity evidence before any platform write action. Candidates identified only by a text fingerprint may continue through the legacy local collection flow, but they cannot be favorited automatically and must be reported as identity-incomplete; changing legacy deduplication will be handled separately.
