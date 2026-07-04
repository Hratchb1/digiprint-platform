# Screen: Login

**Audience:** all readers · **Route:** `/login` · **Component:** `frontend/src/pages/LoginPage.tsx`

## Purpose
Staff sign-in. Every other screen requires a logged-in user (routes are wrapped in `PrivateRoute`; unauthenticated visitors are redirected here).

## Layout & fields
Dark card with the digiPrint logo and an orange accent bar over a film-grain background.

| Field | Rules |
|---|---|
| Email | Required, email format, autofocused |
| Password | Required; show/hide toggle (eye icon) |

**Sign in** button — disabled with "Signing in…" while the request is in flight.

## Behaviour
- Submits to `POST /api/auth/login`. On success the JWT and user object are stored in `localStorage` (via `useAuth`) and the app navigates to `/dashboard`.
- On failure an inline red alert shows the server's message (e.g. "Invalid email or password") or a generic fallback.
- Sessions last 8 hours (JWT expiry). Any API call returning 401 afterwards clears storage and bounces back to this screen automatically (Axios response interceptor in `lib/api.ts`).

## States
- **Loading:** button label "Signing in…", disabled.
- **Error:** red alert box above the form.
- No sign-up or password-reset flow — accounts are provisioned by an admin (see `backend/app/seed_admin.py` / user management is DB-side for now).
