# Changelog

## Unreleased

### Fixed

- Jira assignee/reporter tags now use `displayName` from the issue payload, the
  same as the original connector-engine. Email is an optional extra field read
  only when already present; it is never required to capture the name. Syncs
  log source-to-tag and persisted-tag completeness, and reject partial
  bulk-fetch responses.
- Jira comments are fully paginated, ADF mentions/status/emoji/links become
  readable text, title/description/comments are read from the issue payload
  independently, and Jira 429s retry with Retry-After / backoff.
- Ask can list exact ticket keys for a filter (label, assignee, status, …).
  Counts no longer strand the model without IDs.
- Catalog queries use a published field allow-list (including parent and
  duedate). Names use contains; key/parent/status/dates are exact. Find/count
  support AND filters. Email tags are never queryable or returned.
