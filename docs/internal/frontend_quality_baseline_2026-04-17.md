# Frontend Quality Baseline (2026-04-17)

## Environment

- Local `node/npm` were unavailable initially.
- Baseline was captured using local portable Node.js (`v20.19.0`) in workspace session.

## Commands

```powershell
cd frontend
npm ci
npm run typecheck -- --pretty false
npx eslint "src/**/*.{ts,tsx,js,jsx}" --no-error-on-unmatched-pattern
```

## Baseline Result

- `typecheck`: **1 error**
  - `src/pages/__tests__/Traceability.test.tsx:99` (`TraceabilityBackfillResult` shape mismatch)
- `eslint`: **7 findings**
  - `5 errors`
  - `2 warnings`

## Notes

- `npm run lint` currently shells through `python3 ../scripts/check_bom.py`; this fails on Windows shells where `python3` alias is not present.
- For cross-platform local verification without global Node install, use:
  - [docs/runbooks/frontend-verification.md](../runbooks/frontend-verification.md)
  - `python scripts/verify_frontend.py --mode all`
