# RFC: JWT storage — from localStorage to httpOnly cookie

Status: draft (wave E4 of docs/SHOULD_FIX_ROADMAP.md; implementation
pending approval). Scope: backend auth issuance, frontend axios layer,
e2e flows.

## Problem

The access token lives in `localStorage` (`services/api/client.ts`,
`store/authSlice.ts`, three writers in `pages/Login.tsx`):

- any XSS on the page exfiltrates a bearer token valid for 30+ minutes;
- there is no refresh or revocation: a 401 always ends the session, and
  logout cannot invalidate a stolen token server-side;
- `client.ts` declares an "auth refresh" that does not exist.

## Proposal

1. **httpOnly, SameSite=Strict cookie** issued by `/auth/login` (and
   OAuth callbacks / MFA verify-login) alongside the JSON body during
   migration; the frontend stops reading/writing the token entirely.
2. **Short access token (5–10 min) + refresh token** (httpOnly cookie,
   7–30 days, rotating on use). Refresh endpoint: `POST /auth/refresh`.
3. **Server-side revocation**: `token_sessions` table (user_id, refresh
   token hash, expires_at, revoked_at); logout revokes the session;
   "logout everywhere" revokes all. Password change revokes all.
4. **CSRF**: SameSite=Strict + custom `X-Requested-With` header check on
   mutating routes (cookie auth re-introduces CSRF surface).
5. **WebSocket tickets**: `POST /auth/ws-ticket` must accept the cookie
   (today it requires a Bearer header, and `client.ts` reads the token
   from localStorage) - a dedicated client + endpoint migration step,
   not a transparent switch.

## Migration steps (each shippable independently)

- M1: backend issues cookie in addition to the body (dual mode).
- M2: frontend `client.ts` drops the Authorization header, relies on
  cookies; `withCredentials` for cross-origin deployments.
- M3: refresh rotation + `token_sessions` + logout revocation.
- M4: body token removed; `ACCESS_TOKEN_EXPIRE_MINUTES` lowered.
- Rollback at each step: previous mode remains until the next step.

## Risks / open questions

- Cross-origin mode (if the Vite proxy is dropped) needs `credentials:
  include`, CORS origins that actually include the dev origin (today the
  list has :3000/:5173 but NOT :3001), and `X-Requested-With` added to
  the allowed CORS headers - none of which exist yet.
- Service-to-service scoped tokens keep the `Authorization` header path
  (they are machine clients, not browsers).
- Pen-test of the CSRF header check before M2.

## Non-goals

- Changing token cryptography (HS256 stays; see roadmap B for key KDF).
- SSO/OAuth provider flows beyond issuing the cookie at the end.
