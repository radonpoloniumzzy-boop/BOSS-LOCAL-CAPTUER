# Recruiting Candidate Capture

This context covers discovering recruiting candidates, screening their fit for a role, preserving suitable candidates on the recruiting platform, and prioritizing later contact.

## Candidates and identity

**Candidate**:
A person discovered on a recruiting platform who may be evaluated for one or more roles.
_Avoid_: Card, record, friend

**Platform Identity**:
The platform-issued identity evidence used to recognize a Candidate across batches and perform platform actions. Text similarity may suggest a duplicate but is not a Platform Identity.
_Avoid_: Name fingerprint, candidate name

**Recruiting Relationship**:
The platform relationship between the recruiter and a Candidate, which may have its own relationship identifier such as `friendId`. It is not the Candidate's identity.
_Avoid_: Candidate identity, platform UID

## Collection and screening

**Capture Batch**:
The set of candidate observations imported by one collection operation from a recruiting page.
_Avoid_: Screening run, favorite batch

**Screening Profile**:
The role-specific criteria and prompt used to evaluate Candidates for a particular role.
_Avoid_: Global rating standard

**Initial Screening**:
The role-specific evaluation applied to Candidates collected from a recommendation page to decide whether they should enter the Favorite Pool.
_Avoid_: Review, contact ranking

**Favorite Eligibility Policy**:
The per-role, user-configurable set of Initial Screening ratings eligible for native favorite actions. A role without this configuration cannot run automatic favorites.
_Avoid_: Hard-coded rating threshold, global rating rule

## Favorites and later review

**Native Favorite**:
The recruiting platform's own favorite state for a Candidate. Success is defined by the Candidate being present in the platform's favorite management experience, not by a local-only marker or a particular private API response.
_Avoid_: Local favorite, saved row

**Favorite Action**:
One attempt to establish or verify a Candidate's Native Favorite state. Its outcome may be success, explicit failure, or unknown.
_Avoid_: Screening result

**Source Page Context**:
The original recruiting-platform tab and recommendation-page state from which a Capture Batch was collected. The first Native Favorite milestone requires this context to remain valid until all Favorite Actions for the batch finish.
_Avoid_: Any Boss tab, browser session

**Favorite Pool**:
The set of Candidates preserved through Native Favorites so they can be reviewed and contacted later without depending on the recommendation page.
_Avoid_: Contact queue

**Single-Batch Favorite Mode**:
A run that captures, screens, and favorites one Capture Batch, then stops before loading another batch.
_Avoid_: Manual favorite

**Continuous Favorite Mode**:
A later operating mode that repeats the single-batch workflow until stopped or automatically paused by an exceptional platform state.
_Avoid_: Batch favorite

**Secondary Screening**:
The later evaluation of Candidates collected from the Favorite Pool to determine contact suitability, priority, and questions to verify.
_Avoid_: Initial screening

**Contact Priority**:
The role-specific ordering signal produced by Secondary Screening for deciding whom to contact and when. It is distinct from screening rating and Native Favorite state.
_Avoid_: Candidate rating
