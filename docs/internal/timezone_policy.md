# Timezone-Aware Datetime Policy

## Scope
Applies to backend code, background jobs, and timestamp-related tests in this repository.

## Policy
- Use `datetime.now(timezone.utc)` for new UTC timestamps.
- Store and serialize timestamps as timezone-aware values whenever the model or API contract carries a point in time.
- Normalize parsed datetimes to UTC before comparing them with database values or other timestamps.
- Do not introduce new `datetime.utcnow()` call sites.
- When existing payloads expose timestamp strings, include an explicit offset such as `+00:00`.

## Testing
- Add regression tests for any code path that serializes or persists sync timestamps.
- Prefer assertions on ISO-8601 strings with offsets over naive string comparisons.

## Notes
- The codebase still contains a few legacy timestamp helpers; they should behave as UTC-aware wrappers and should not be expanded for new code.
