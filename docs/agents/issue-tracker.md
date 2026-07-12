# Issue Tracker: GitHub

Issues, PRDs, bugs, and follow-up tasks for this repo live as GitHub Issues.

Use the `gh` CLI from inside this clone. The repo is inferred from `git remote -v`.

## Conventions

- Create an issue: `gh issue create --title "..." --body "..."`
- Read an issue: `gh issue view <number> --comments`
- List issues: `gh issue list --state open --json number,title,body,labels,comments`
- Comment on an issue: `gh issue comment <number> --body "..."`
- Apply a label: `gh issue edit <number> --add-label "..."`
- Remove a label: `gh issue edit <number> --remove-label "..."`
- Close an issue: `gh issue close <number> --comment "..."`

Use heredocs or body files for multi-line issue bodies.

## Pull Requests As A Request Surface

PRs as a request surface: no.

If this repo later treats external PRs as feature requests, change this line to `yes` and route PRs through the same triage labels and states as issues.

## Skill Phrases

When a skill says "publish to the issue tracker", create a GitHub issue.

When a skill says "fetch the relevant ticket", run `gh issue view <number> --comments`.

## Wayfinding

If a wayfinding map is needed, create a GitHub issue labelled `wayfinder:map`.

Child tickets should be GitHub issues linked to that map. If GitHub sub-issues are unavailable, put `Part of #<map>` at the top of the child issue body and add the child to a task list in the map issue.

