# Domains and DNS

Target layout for `timeismetime.com`:

| Host | Serves | Hosted on |
|---|---|---|
| `app.timeismetime.com` | The MirrorSelf web app | Vercel project `mirrorself-web` |
| `www.timeismetime.com` | Public website (for now: the same app, until a separate site exists) | Vercel project `mirrorself-web` |
| `timeismetime.com` | Redirect to `www` | Vercel (308 redirect, already configured) |
| `api.timeismetime.com` | The API | Render service `mirrorself-api` |

## Current state (checked 2026-11-17)

DNS is hosted at Hostinger (`ns1.dns-parking.com`, `ns2.dns-parking.com`).

| Host | DNS today | Result |
|---|---|---|
| `www` | CNAME → `a9eae9b403a1e426.vercel-dns-017.com` | **Works.** HTTPS, valid certificate, serves the app. |
| apex `timeismetime.com` | A → `2.57.91.91` (Hostinger parking) | **Broken.** HTTP shows Hostinger's "Parked Domain" page; HTTPS fails the TLS handshake. Vercel already has the domain with a 308 redirect to `www`, but DNS does not point at Vercel, so it never takes effect. |
| `app` | no record | Does not resolve. |
| `api` | no record | Does not resolve. |

No conflicts: neither `app` nor `api` is attached to any other Vercel or Render
project.

## Records to add at Hostinger

Hostinger → Domains → `timeismetime.com` → **DNS / Nameservers** → DNS records.

| # | Type | Name | Value | TTL | Effect |
|---|---|---|---|---|---|
| 1 | A | `@` | `216.198.79.1` | 3600 | Apex goes to Vercel, which redirects to `www`. **Replaces** the existing `@ A 2.57.91.91` parking record; delete that one. |
| 2 | A | `@` | `64.29.17.1` | 3600 | Second address for the same (Vercel recommends both). |
| 3 | CNAME | `app` | `a9eae9b403a1e426.vercel-dns-017.com` | 3600 | `app` goes to Vercel. |
| 4 | CNAME | `api` | `mirrorself-api.onrender.com` | 3600 | `api` goes to Render. |

Leave the existing `www` CNAME and any MX/TXT (email) records untouched.

Record 1 replaces a live record, which is why this needs the owner's go-ahead:
the only thing it changes is the parked page on the bare domain, which is
broken over HTTPS today.

## Platform steps (done in order)

1. **Vercel:** add `app.timeismetime.com` to project `mirrorself-web`.
   Prepared in the API: `add_project_domain`. Harmless before DNS exists; it
   simply shows as unverified.
2. **Render:** add `api.timeismetime.com` as a custom domain on
   `mirrorself-api` (Dashboard → service → Settings → Custom Domains). The
   Render connector available here cannot add custom domains, so this is a
   dashboard step for the owner. Render issues the certificate once the CNAME
   resolves.
3. **Hostinger:** add records 1–4.
4. **Wait for DNS and certificates**, then verify (below).
5. **Point the app at the new API host:** set Vercel
   `EXPO_PUBLIC_API_URL=https://api.timeismetime.com` and redeploy. Do this
   only after step 4 verifies, and keep `mirrorself-api.onrender.com` working
   (it does not go away).
6. **Supabase:** Authentication → URL Configuration. Set **Site URL** to
   `https://app.timeismetime.com` and add these to **Redirect URLs**:
   `https://app.timeismetime.com/**`, `https://www.timeismetime.com/**`,
   `https://mirrorself-web.vercel.app/**`. The app sends the current origin as
   the magic-link redirect, so every origin it is served from must be listed.
7. **CORS:** already allows `app.`, `www.`, the apex and the Vercel alias
   (`render.yaml`, `CORS_ALLOW_ORIGINS`).

## Verification

Do not call a domain configured until every line passes:

```bash
nslookup app.timeismetime.com 8.8.8.8
nslookup api.timeismetime.com 8.8.8.8
curl -sSI https://timeismetime.com          # expect 308 → https://www.timeismetime.com/
curl -sSI https://app.timeismetime.com      # expect 200, valid certificate
curl -sS  https://api.timeismetime.com/v1/health   # expect {"status":"ok"}
python apps/api/scripts/e2e_smoke.py --base-url https://api.timeismetime.com \
    --origin https://app.timeismetime.com --origin https://www.timeismetime.com
```

Then sign in on `https://app.timeismetime.com` with a magic link and open a
conversation.

## Rollback

Each step is independently reversible: delete the DNS record, remove the
domain from Vercel/Render, or set `EXPO_PUBLIC_API_URL` back to
`https://mirrorself-api.onrender.com` and redeploy. The `.onrender.com` and
`.vercel.app` hosts keep working throughout.

## Later: a separate public site on `www`

When a marketing site exists, give it its own Vercel project, move
`www.timeismetime.com` (and the apex redirect) to it, and keep `app.` on
`mirrorself-web`. Until then `www` serving the app is intentional.
