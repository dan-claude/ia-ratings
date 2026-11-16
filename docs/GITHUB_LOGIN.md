# Setting up "Continue with GitHub" login

IA Film Rater can offer GitHub sign-in **alongside** its normal login
(`AUTH_SCHEME=ia` archive.org login, or `local` email/password). GitHub login is
off until you give the server an OAuth app's credentials; once configured, the
login screen shows a **Continue with GitHub** button under the usual form.

You create one GitHub OAuth App **per environment** (a local-dev app and a
production app), because each app has exactly one callback URL.

## 1. Create the OAuth App on GitHub

1. GitHub → your avatar → **Settings** → **Developer settings** → **OAuth Apps**
   → **New OAuth App**. (To own it under an organization, use the
   organization's Settings instead.)
2. Fill in:
   - **Application name** — e.g. `IA Film Rater` (`IA Film Rater (dev)` for the local app). Users see this on the consent screen.
   - **Homepage URL** — the site's base URL (see the table below).
   - **Authorization callback URL** — the base URL **plus `/api/auth/github/callback`**, exactly:

   | Environment | Homepage URL | Authorization callback URL |
   |---|---|---|
   | Local dev (Vite) | `http://localhost:5173` | `http://localhost:5173/api/auth/github/callback` |
   | Local, built client served by Flask | `http://localhost:5001` (whatever port Flask reports) | `http://localhost:5001/api/auth/github/callback` |
   | Production (Railway) | `https://<your-domain>` | `https://<your-domain>/api/auth/github/callback` |

   Use `localhost` consistently — not `127.0.0.1` — in the browser address bar
   and in the callback URL; they are different origins, and the login cookie
   would not follow the redirect.
3. Leave **Enable Device Flow** unticked. Click **Register application**.
4. On the app page, note the **Client ID**, then click **Generate a new client
   secret** and copy it immediately (GitHub shows it only once).

The app requests **no scopes**: it only reads the public profile (numeric
account id and username). It never sees the user's email address.

## 2. Give the server the credentials

Two environment variables turn the feature on (both are required):

| Variable | Value |
|---|---|
| `GITHUB_CLIENT_ID` | the app's Client ID |
| `GITHUB_CLIENT_SECRET` | the generated client secret — keep it private, never commit it |

### Local development

```bash
export GITHUB_CLIENT_ID=...        # dev app's client id
export GITHUB_CLIENT_SECRET=...    # dev app's client secret
make dev                           # Flask (port 5001 if 5000 is taken)
cd client && npm run dev           # then open http://localhost:5173
```

Use the Vite URL (`http://localhost:5173`) so the callback URL above matches;
Vite proxies `/api` to Flask, including the OAuth redirects.

### Production (Railway)

In the Railway service → **Variables**, add `GITHUB_CLIENT_ID` and
`GITHUB_CLIENT_SECRET` (from the *production* OAuth app). Railway redeploys
automatically. Make sure `SESSION_SECRET` is set too (see `CLAUDE.md`).

## 3. Check it works

- `GET /api/config` returns `"oauth_providers": ["github"]`.
- The login page shows **Continue with GitHub**; clicking it goes to GitHub,
  and after approving you land back in the app signed in.
- A new row appears in the admin **Users** tab with `github_username` filled in.

## How accounts behave

- A GitHub account is identified by its **numeric id**, so renaming the GitHub
  user keeps the same IA Film Rater account (the stored username is refreshed on
  each login).
- Each login method creates its **own** account. Someone who has signed in with
  both archive.org and GitHub has two separate accounts and two separate sets of
  ratings; accounts are deliberately not merged automatically.
- GitHub-created users are not admins. Promote one from the admin **Users** tab,
  or with `python tools/print_db.py --make-admin <email>` using the synthetic
  email shown there (`<github-id>+<username>@users.noreply.github.com`).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| No GitHub button | `GITHUB_CLIENT_ID` or `GITHUB_CLIENT_SECRET` missing, or the server wasn't restarted. Check `/api/config`. |
| GitHub says *redirect_uri is not associated with this application* | The callback URL on the OAuth app doesn't exactly match the URL you're browsing from (scheme, host, port, path). |
| "GitHub sign-in expired or was invalid" | The login cookie didn't come back: mixed `localhost`/`127.0.0.1`, an older tab, or the 8-hour session lapsed. Start again from the login page. |
| "Could not sign in with GitHub" | The code/secret exchange failed — usually a wrong client secret, or the server can't reach github.com. Details are in the server log (`github.login.failed`). |
| Works locally, fails in production over `http://` | Use the `https://` Railway domain in both GitHub's callback URL and the browser. |

## Optional: `GITHUB_REDIRECT_URI`

Normally leave this unset: GitHub then uses the callback URL registered on the
OAuth app. Set it only if you registered more than one callback URL and need to
pick one; the value must be one of them.

## Rotating the secret

Generate a new client secret on the OAuth app page, update
`GITHUB_CLIENT_SECRET`, redeploy, then delete the old secret on GitHub.
