# Tech Stack Reference

A copy-paste guide for spinning up a new app with the same setup we used for Arc.

This doc covers:
1. The full stack (what's running and why)
2. Connecting to Supabase (and the IPv4 trap that wastes hours)
3. Local development with a phone over an unreliable network

---

## 1. The Stack

### Mobile

| Layer | Tool | Why |
|---|---|---|
| Framework | Expo SDK 54 | Cross-platform, no Xcode needed in early dev |
| Language | TypeScript | Catches errors at compile time |
| Routing | Expo Router (file-based) | Routes are folders/files; layouts compose naturally |
| Runtime | React Native 0.81 + React 19.1 | Latest stable as of early 2026 |
| Fonts | `@expo-google-fonts/*` (Playfair Display + Inter) | Brand typography |
| Icons | `lucide-react-native` | 1.75px stroke, rounded caps, matches calm UI |
| Auth storage | `expo-secure-store` | iOS Keychain for JWTs (encrypted) |
| Image / camera | `expo-image-picker` (with `exif: true`) | Reads photo metadata for auto-fill |
| Audio recording | `expo-audio` | Modern hooks-based API, replaces deprecated `expo-av` |
| Video playback | `expo-video` | Native controls, replaces `expo-av` |
| Media library | `expo-media-library` | Reads video creation time / GPS (image-picker can't) |
| Location | `expo-location` | Reverse geocoding via Apple's on-device geocoder (no API key) |
| Biometric lock | `expo-local-authentication` | Face ID / Touch ID / passcode fallback |
| Date picker | `@react-native-community/datetimepicker` | Native iOS picker |
| Local KV | `expo-secure-store` (key→string) | Per-device preferences (lock, durations, etc.) |

### Backend

| Layer | Tool | Why |
|---|---|---|
| Web framework | FastAPI 0.115 | Pydantic for validation, async by default |
| HTTP client | `httpx` (async) | Calls Supabase REST API with the user's JWT |
| Settings | `pydantic-settings` | Loads `.env.local` into typed config |
| Server | `uvicorn` (with `--reload` for dev) | Standard ASGI |
| Tests | `pytest` | Pure-function unit tests on detectors / engine logic |
| Python | 3.13 (via Homebrew) | 3.10+ required for `str \| None` syntax |

The backend is **deliberately a thin layer** over Supabase. The mobile app sends the user's JWT to FastAPI, FastAPI forwards it to Supabase REST, RLS does the access control. FastAPI's job is business logic and any future Claude calls — it doesn't need to know about specific tables.

### Database / storage / auth

| Layer | Tool |
|---|---|
| Database | Supabase Postgres |
| Auth | Supabase Auth (email/password to start) |
| File storage | Supabase Storage (private bucket, RLS-scoped) |
| Row-level security | Postgres RLS, all tables locked to `auth.uid()` |
| Migrations | Plain SQL files in `supabase/migrations/`, applied via `psql` |

### Dev environment glue

| Tool | Why |
|---|---|
| `cloudflared` | Tunnel local FastAPI to a public HTTPS URL (more on this below) |
| Expo `--tunnel` mode | Same idea for the Metro bundler |
| `gh` CLI | One-command GitHub auth (alternative to SSH keys) |
| Homebrew | All system deps (`node`, `python@3.13`, `cloudflared`, `gh`, `libpq`) |

### Future production (planned, not yet wired)

- Digital Ocean droplet for the FastAPI server (existing infra)
- Stripe Checkout (web subscriptions, "reader app" pattern to bypass Apple's 30%)
- Claude API for narrative generation (Weekly Arc reflections, etc.)
- Brevo for email
- Expo EAS Build for proper iOS dev clients (Face ID Info.plist, app icon, etc.)

---

## 2. Connecting to Supabase

### Three keys, different uses

In `Settings → API` you'll find:

| Key | Where it goes | Power |
|---|---|---|
| **Project URL** | Both backend and mobile (`SUPABASE_URL`) | Just the host |
| **Publishable key** (formerly `anon`) | Both backend and mobile (`SUPABASE_ANON_KEY`) | Public; subject to RLS |
| **Secret key** (formerly `service_role`) | **Backend only** (`SUPABASE_SERVICE_ROLE_KEY`) | Bypasses RLS — never put in mobile app |

The publishable key is **safe to ship in the mobile bundle**. RLS is what keeps users isolated; the key just identifies the project.

### Environment file structure

Two-file pattern, repo-wide:

```
.env.example   ← committed, placeholder values
.env.local     ← gitignored, real values
mobile/.env.example
mobile/.env    ← gitignored, real values for Expo (EXPO_PUBLIC_* prefix)
```

`.gitignore` already excludes `.env`, `.env.local`, `*.env` and explicitly `!.env.example`.

For the mobile, all env vars must be prefixed `EXPO_PUBLIC_` for the bundler to embed them.

### Database connection string — the IPv4 trap

This is the part that wastes 2 hours if you don't know.

**The "Direct connection" URI from the dashboard:**
```
postgresql://postgres:[PASSWORD]@db.PROJECT_REF.supabase.co:5432/postgres
```

**This is IPv6-only.** Most home / corporate / hotspot networks are IPv4-only, and your laptop will silently fail to connect:

```
psql: error: could not translate host name "db.xxx.supabase.co" to address:
nodename nor servname provided, or not known
```

```bash
$ dig +short db.xxx.supabase.co A      # ← IPv4
                                        # (empty — there is no IPv4 record)
$ dig +short db.xxx.supabase.co AAAA   # ← IPv6
2600:1f16:1cd0:3341:5743:a3d5:24e8:a14c
```

**The fix: use the Session pooler instead.** It has IPv4 and works the same way for migrations.

In the Supabase dashboard: **Settings → Database → Connection string → Session pooler tab**. The URI looks like:
```
postgresql://postgres.PROJECT_REF:[PASSWORD]@aws-1-REGION.pooler.supabase.com:5432/postgres
```

Note three differences from direct connection:
1. Hostname is `aws-1-REGION.pooler.supabase.com` (regional pooler)
2. Username is `postgres.PROJECT_REF` (your project ref baked in)
3. Same `:5432` port — the **session** pooler. (There's also a **transaction** pooler at `:6543` for app runtime; sessions are right for migrations.)

Some older or "aws-0-" variants exist depending on when the project was created. If `aws-0-...` returns *"Tenant or user not found"*, try `aws-1-...`.

**URL-encode your password** if it has special characters. The character `%` must become `%25`, `@` must become `%40`. Practical example: if your password is `G458Bu9*y%w`, the URI password segment is `G458Bu9*y%25w`.

### What to use the connection string for

- **Migrations** (`psql "$DATABASE_URL" -f migrations/0001_x.sql`) — yes, session pooler
- **Application runtime queries** — don't connect from FastAPI directly; use Supabase REST via `httpx` and forward the user's JWT. RLS handles auth, no `DATABASE_URL` needed.

### Production note

When the FastAPI backend is deployed (e.g., Digital Ocean), use the **transaction pooler at `:6543`** for connection-from-app traffic. It multiplexes connections so the app scales past Supabase's ~60-direct-connection cap.

```
postgresql://postgres.PROJECT_REF:[PASSWORD]@aws-1-REGION.pooler.supabase.com:6543/postgres
```

But again — this only matters if your backend is making direct DB connections. If it's only calling Supabase REST (recommended), the connection string is just for migrations.

### RLS pattern

Every user-scoped table gets:

```sql
create table foo (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid()
    references public.profiles(id) on delete cascade,
  -- ... other columns ...
  created_at timestamptz not null default now()
);

alter table foo enable row level security;

create policy "Users can view their own foos"
  on foo for select using (auth.uid() = user_id);
create policy "Users can insert their own foos"
  on foo for insert with check (auth.uid() = user_id);
create policy "Users can update their own foos"
  on foo for update using (auth.uid() = user_id);
create policy "Users can delete their own foos"
  on foo for delete using (auth.uid() = user_id);
```

The `default auth.uid()` on `user_id` means clients **don't have to send their own user_id** — the DB fills it in from the JWT. Combined with RLS's `auth.uid() = user_id` check, this both eliminates a class of bugs (forgetting to set user_id) and prevents a class of attacks (sending someone else's user_id).

**Auto-create a profile row on signup** via a trigger:

```sql
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public
as $$
begin
  insert into public.profiles (id) values (new.id);
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
```

### Storage bucket pattern

```sql
insert into storage.buckets (id, name, public)
  values ('app-media', 'app-media', false)
  on conflict (id) do nothing;

create policy "Users can upload to their own folder"
  on storage.objects for insert
  with check (
    bucket_id = 'app-media'
    and (storage.foldername(name))[1] = auth.uid()::text
  );
-- + select / update / delete policies same shape
```

Then in mobile, upload paths like `{user_id}/{entry_id}/{random}.{ext}`. The first folder segment encodes the user; RLS enforces it.

For uploads from React Native:
```ts
const form = new FormData();
form.append('file', {
  uri: localUri,
  type: mimeType,
  name: filename,
} as unknown as Blob);

await fetch(`${SUPABASE_URL}/storage/v1/object/${BUCKET}/${path}`, {
  method: 'POST',
  headers: {
    apikey: ANON_KEY,
    Authorization: `Bearer ${userJwt}`,
    // No Content-Type header — fetch sets the multipart boundary
  },
  body: form,
});
```

For viewing private files: get a signed URL via `POST /storage/v1/object/sign/{bucket}/{path}` with `{expiresIn: 3600}`.

### File size limits

- Free plan: **50 MB per object** project-wide
- Pro plan: configurable up to several GB

Even on Pro, you must explicitly raise the limit in the dashboard:
**Settings → Storage → File size limit**.

Per-bucket limit can be raised via SQL:
```sql
update storage.buckets
  set file_size_limit = 200 * 1024 * 1024  -- 200 MB
  where id = 'app-media';
```

But the project-wide setting in the dashboard is still the hard ceiling. Both must be raised.

---

## 3. Local development environment

### The problem

You're running FastAPI on your laptop. Your phone is on the same wifi. The phone needs to call your laptop's API. Two things can break:

1. **Your network blocks LAN-to-LAN traffic** (corporate wifi, hotspots, some ISPs with carrier-grade NAT, networks with VPN client isolation). Your phone literally can't see your laptop's local IP.
2. **Your IP changes when you move** (coffee shop → home → tethering). Even if you hardcode the laptop IP in your mobile config, it goes stale.

The fix for both: tunnel the FastAPI through `cloudflared`. Your phone hits a public HTTPS URL that proxies to your localhost. Network topology becomes irrelevant.

### Setup (one-time)

```bash
brew install cloudflared
```

No signup, no Cloudflare account. Quick tunnels are free and ephemeral.

### Run

```bash
cloudflared tunnel --url http://localhost:8000 --no-autoupdate
```

Watch for the line:
```
Your quick Tunnel has been created! Visit it at:
https://gorgeous-isolated-bowl-qualities.trycloudflare.com
```

That URL proxies to localhost:8000. New URL each session.

### The dev orchestrator script

The whole stack — FastAPI + cloudflared + Expo with tunnel — is one command. Save as `scripts/dev.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

UVICORN_PID=""
CLOUDFLARED_PID=""

cleanup() {
  [[ -n "$UVICORN_PID"     ]] && kill "$UVICORN_PID"     2>/dev/null || true
  [[ -n "$CLOUDFLARED_PID" ]] && kill "$CLOUDFLARED_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# 1. FastAPI
lsof -ti:8000 | xargs -r kill -9 2>/dev/null || true
sleep 1
.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload --log-level warning &
UVICORN_PID=$!
until curl -s -f http://127.0.0.1:8000/health >/dev/null 2>&1; do sleep 1; done

# 2. Cloudflared, capture URL
TUNNEL_LOG="$(mktemp)"
cloudflared tunnel --url http://localhost:8000 --no-autoupdate >"$TUNNEL_LOG" 2>&1 &
CLOUDFLARED_PID=$!

TUNNEL_URL=""
for _ in $(seq 1 60); do
  # The `|| true` keeps `set -e` + `pipefail` from killing us on no-match.
  TUNNEL_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1 || true)
  [[ -n "$TUNNEL_URL" ]] && break
  sleep 1
done

# 3. Auto-update mobile/.env with the fresh URL
ENV_FILE="$ROOT/mobile/.env"
if grep -q '^EXPO_PUBLIC_API_URL=' "$ENV_FILE" 2>/dev/null; then
  sed -i '' "s|^EXPO_PUBLIC_API_URL=.*|EXPO_PUBLIC_API_URL=$TUNNEL_URL|" "$ENV_FILE"
else
  echo "EXPO_PUBLIC_API_URL=$TUNNEL_URL" >>"$ENV_FILE"
fi

# 4. Expo
cd "$ROOT/mobile"
exec npx expo start --tunnel
```

Then `chmod +x scripts/dev.sh && ./scripts/dev.sh`. One terminal runs the whole stack.

### Mobile API base URL resolution

The mobile app picks its API URL from environment (or falls back to the LAN host Expo is using):

```ts
// mobile/lib/api.ts
import Constants from 'expo-constants';

function resolveApiBaseUrl(): string {
  const override = process.env.EXPO_PUBLIC_API_URL;
  if (override) return override;

  // Fallback: derive from Expo's host (works on real LAN, fails behind
  // restrictive networks — that's why we set EXPO_PUBLIC_API_URL).
  const hostUri =
    Constants.expoConfig?.hostUri ??
    Constants.expoGoConfig?.hostUri ??
    Constants.manifest?.hostUri;
  if (hostUri) {
    const host = hostUri.split(':')[0];
    return `http://${host}:8000`;
  }
  return `http://localhost:8000`;
}
```

`dev.sh` writes the cloudflared URL into `mobile/.env`'s `EXPO_PUBLIC_API_URL` so the override always wins on dev builds.

### Expo Go vs custom dev client

Expo Go is great for the first few weeks. Two limits eventually push you to a custom dev client (built via EAS Build):

1. **Face ID / biometric prompts** — Expo Go's `Info.plist` doesn't always expose `NSFaceIDUsageDescription` cleanly. Calls fall back to passcode silently. A custom build with your own `app.json` infoPlist gets proper Face ID.
2. **Native modules outside the Expo Go bundle** — anything not on Expo's prebuilt list requires a dev client.

For Arc, we ran on Expo Go through the entire build; the passcode fallback was acceptable. EAS dev client is a 30-min setup when you're ready.

---

## 4. Recommended directory layout

```
your-app/
├── .env.example
├── .env.local                      ← gitignored
├── .gitignore
├── README.md
├── scripts/
│   └── dev.sh                      ← the orchestrator above
├── supabase/
│   └── migrations/
│       ├── 0001_initial_schema.sql
│       ├── 0002_*.sql
│       └── ...
├── backend/
│   ├── __init__.py
│   ├── main.py                     ← FastAPI app, route registration, CORS
│   ├── config.py                   ← Pydantic Settings reading .env.local
│   ├── auth.py                     ← bearer-token dependency
│   ├── database.py                 ← httpx client preconfigured for Supabase REST
│   ├── models.py                   ← Pydantic request/response models
│   ├── routes/
│   │   ├── __init__.py
│   │   └── *.py                    ← one file per resource
│   ├── services/
│   │   ├── __init__.py
│   │   └── *.py                    ← business logic, pure functions
│   ├── tests/
│   │   ├── __init__.py
│   │   └── test_*.py               ← pytest, no DB
│   └── requirements.txt
└── mobile/
    ├── app.json                    ← Expo config + iOS infoPlist permissions
    ├── package.json
    ├── tsconfig.json
    ├── .env.example
    ├── .env                        ← gitignored, EXPO_PUBLIC_* vars
    ├── app/                        ← Expo Router screens
    │   ├── _layout.tsx             ← root layout: fonts, providers, lock screen
    │   ├── index.tsx               ← redirect logic (auth or home)
    │   ├── (auth)/
    │   │   ├── _layout.tsx         ← redirects authed users to /(app)
    │   │   ├── welcome.tsx
    │   │   ├── sign-in.tsx
    │   │   └── sign-up.tsx
    │   └── (app)/
    │       ├── _layout.tsx         ← redirects unauthed users to /(auth)
    │       └── *.tsx               ← screens
    ├── components/                 ← reusable UI primitives
    ├── constants/
    │   ├── theme.ts                ← design tokens (colors, type, spacing, shadows)
    │   └── ...
    ├── contexts/                   ← React contexts (auth, profile, etc.)
    └── lib/
        ├── api.ts                  ← typed REST client to FastAPI
        ├── auth-storage.ts         ← SecureStore wrappers + JWT decode
        ├── auth-events.ts          ← pub/sub bridge for unauthorized signal
        └── supabase-auth.ts        ← direct Supabase Auth calls (signup/signin/refresh)
```

---

## 5. Common gotchas (chronological from our build)

1. **IPv4 / IPv6 on `db.PROJECT.supabase.co`** → use Session pooler (above).
2. **PostgREST PGRST102 "All object keys must match"** when bulk-upserting — every record in the array must have the **same set of keys**. Don't conditionally add fields per-record.
3. **PostgREST PATCH/DELETE require an explicit filter.** Even with RLS scoping you to your own row, you must include something like `?id=eq.X`. Without it, PostgREST refuses.
4. **JWT refresh** — Supabase access tokens last 1 hour. Implement silent refresh using the stored refresh token before each request, or your users get bounced to sign-in every hour.
5. **Storage uploads from RN need `FormData` with `{uri, type, name}`.** Don't try to read the file as base64 first; let `fetch` build the multipart.
6. **`videoQuality` in `expo-image-picker`** only applies when launching the camera, *not* when picking from the library. Library-picked videos arrive at original size.
7. **Expo Go Face ID** silently falls back to passcode unless the user explicitly grants Expo Go Face ID access in iOS Settings → Face ID & Passcode → Other Apps. Custom dev clients via EAS Build solve this properly.
8. **`autoFocus` on iOS TextInput** can cause weird scroll/keyboard timing — use it on welcome forms, not on inputs revealed by toggles mid-form.
9. **PNG file paths starting with `.`** are hidden in macOS Finder — `Cmd + Shift + .` toggles visibility. Surprising amount of confusion saved by knowing this when editing `.env.local`.
10. **Native modules need a full Expo Go restart** (not just hot-reload). When you `npx expo install` something with native code, swipe Expo Go off the app switcher, re-open, re-scan QR.

---

## 6. The two-file `.env` pattern (full example)

`.env.example` (committed):
```bash
# Supabase API
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=sb_publishable_xxxxxxxxxxxxxxxxxxxxxx
SUPABASE_SERVICE_ROLE_KEY=sb_secret_xxxxxxxxxxxxxxxxxxxxxx

# Session pooler URI for migrations (URL-encode special chars in the password)
DATABASE_URL=postgresql://postgres.your-project-ref:[YOUR-PASSWORD]@aws-1-us-east-2.pooler.supabase.com:5432/postgres
SUPABASE_PROJECT_REF=your-project-ref
```

`.env.local` (gitignored): same shape, real values.

`mobile/.env.example`:
```bash
EXPO_PUBLIC_SUPABASE_URL=https://your-project-ref.supabase.co
EXPO_PUBLIC_SUPABASE_ANON_KEY=sb_publishable_xxxxxxxxxxxxxxxxxxxxxx

# Optional: hard-code the API base URL. dev.sh writes this automatically.
# EXPO_PUBLIC_API_URL=https://random.trycloudflare.com
```

`mobile/.env` (gitignored): same shape, real values. **Never commit this.** Even though `EXPO_PUBLIC_*` vars are public-by-design, your specific publishable key shouldn't be in git history.

---

## 7. Bare-minimum first-day order

1. `brew install node python@3.13 cloudflared gh`
2. Create Supabase project (pick a region close to where you'll deploy)
3. `gh auth login` (so git push just works)
4. `git init && git remote add origin git@github.com:USER/REPO.git`
5. Set up `.env.local` with Project URL, both keys, and the Session pooler URI
6. `psql "$DATABASE_URL"` — confirm it connects (catches the IPv4 thing immediately)
7. Write migration 0001 (profiles, RLS, auto-create-profile trigger)
8. `npx create-expo-app mobile --template default`
9. `npx expo install expo-secure-store @expo-google-fonts/inter @expo-google-fonts/playfair-display`
10. Scaffold `backend/` (FastAPI + httpx + pydantic-settings)
11. Wire `scripts/dev.sh`
12. First commit, first push, first round-trip on phone

That's a day. Day two is features.
