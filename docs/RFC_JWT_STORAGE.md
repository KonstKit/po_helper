# RFC: JWT storage — from localStorage to httpOnly cookie

Status: M1 implemented (httpOnly cookie issuance, dual mode; see the
Resolution log at the bottom). M2 (cookie-based browser session) is
DEFERRED: the implementation surfaced that analytics event
attribution cannot be safely bound to a cookie identity without
server-validated sessions (M3) — multiple cross-tab attribution
races were reproduced in review. M3 and M4 remain pending approval.
Original draft:
(wave E4 of docs/SHOULD_FIX_ROADMAP.md; implementation
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


---

## Resolution log

- 2026-09-05 - M1 implemented: /auth/login, /auth/mfa/verify-login and
  the OAuth callbacks attach the access JWT as an httpOnly,
  SameSite=strict cookie (dual mode: the body token is still returned).
  get_current_user accepts the cookie as a fallback after the
  Authorization header. New POST /auth/logout clears the cookie.
  Settings: AUTH_COOKIE_* (incl. AUTH_COOKIE_FALLBACK_ENABLED, which
  ships OFF: the unchanged frontend logout does not clear the httpOnly
  cookie yet — flip it on together with the M2 frontend). Deployment
  note: set AUTH_COOKIE_SECURE=true behind HTTPS. Login-origin CSRF
  guard added to the middleware stack: /auth/login and
  /auth/mfa/verify-login validate Origin/Referer when present, even
  cookie-less (login CSRF). OAuth callbacks now clear the state cookie
  on the returned response.
- 2026-09-06 - M2 implemented on top of M3 (branch feat/jwt-m1-m2,
  pending batch review): the browser session uses the httpOnly cookie
  (withCredentials, no localStorage token), the boot probe restores the
  session via /v1/users/me, logout calls /auth/logout, the analytics
  owner identity is fed from the confirmed session, and flush gating
  validates the batch owner against the confirmed identity.
- 2026-09-05 - M2 DEFERRED (superseded by the 2026-09-06 entry): the cookie-based browser session requires
  analytics event attribution to be bound to a server-validated
  identity; client-side binding reproduced multiple cross-tab
  attribution races in review (documented in PR #18 discussion).
  Revisit together with M3 (token_sessions + revocation), which gives
  the server-authoritative identity needed to attribute events safely.

