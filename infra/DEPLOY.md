# Sarathi production deployment

Runbook for shipping Sarathi behind TLS on:

- Frontend: `https://sarathi.niheshr.com`  ->  `frontend:3000`
- Backend:  `https://sarathi-api.niheshr.com`  ->  `backend:8000`

Both share the parent domain `niheshr.com`, so a single cookie `Domain=.niheshr.com`
is valid across both subdomains (session cookies set by the API reach the app).

Everything runs from `infra/docker-compose.prod.yml`. One backend image serves
three roles (API, worker, one-shot migrations); the frontend is a separate
Next.js standalone image. Postgres and Redis stay on the internal compose
network and are never published to the host.

## 1. Environment

Config is read from the repo-root `.env` (pydantic-settings). The compose file
force-overrides `APP_ENV`, `DATABASE_URL`, and `REDIS_URL` to the internal hosts,
so you do not edit those for the containers, but everything else comes from `.env`.

Generate a real JWT secret (the app refuses to boot with `change-me` unless
`APP_ENV=dev`):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
# or: openssl rand -base64 48
```

### Env var deltas (dev vs prod)

| Var | Dev value | Prod value | Notes |
| --- | --- | --- | --- |
| `APP_ENV` | `dev` | `prod` | Set by compose; gates the JWT-secret check. |
| `JWT_SECRET` | `change-me` | (48-byte random) | Required in prod; use the command above. |
| `POSTGRES_USER` | (unset, defaults `sarathi`) | `sarathi` | Compose substitutes into the postgres service and `DATABASE_URL`. |
| `POSTGRES_PASSWORD` | (unset) | (strong random) | REQUIRED in prod; compose refuses to start without it. Same generator as `JWT_SECRET`. |
| `POSTGRES_DB` | (unset, defaults `sarathi`) | `sarathi` | Database name. |
| `BACKEND_URL` | `http://localhost:8000` | `https://sarathi-api.niheshr.com` | Used to build the OAuth callback URL. |
| `FRONTEND_URL` | `http://localhost:3000` | `https://sarathi.niheshr.com` | OAuth success redirect target. |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | `["https://sarathi.niheshr.com"]` | JSON list; must include the https app origin. |
| `COOKIE_DOMAIN` | (unset) | `.niheshr.com` | Shares session cookies across app + api subdomains. |
| `WEBAUTHN_RP_ID` | `localhost` | `niheshr.com` | Passkey relying-party id (registrable domain). |
| `WEBAUTHN_ORIGIN` | `http://localhost:3000` | `https://sarathi.niheshr.com` | Passkey origin; must match where the app is served. |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | `https://sarathi-api.niheshr.com` | Frontend BUILD arg (baked into the bundle, not runtime). |
| `STAFF_EMAILS` | (empty) | `niheshr03@gmail.com` | Comma-separated console allowlist. Add teammates as needed. |
| `DATABASE_URL` | `...@localhost:5432/...` | `...@postgres:5432/...` | Set by compose to the internal service host. |
| `REDIS_URL` | `redis://localhost:6379/0` | `redis://redis:6379/0` | Set by compose to the internal service host. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | (empty) | real OAuth creds | From Google Cloud console. |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` | (empty) | at least one real key | Needed for live LLM calls. |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | (empty) | real IAM creds | SES send permission in `ap-south-1`. |
| `AWS_REGION` | `ap-south-1` | `ap-south-1` | SES region. |
| `SES_FROM_ADDRESS` | `no-reply@niheshr.com` | `no-reply@niheshr.com` | Verified SES sender. |

`NEXT_PUBLIC_API_URL` is consumed at `docker compose build` time (compose reads it
from your shell env or the repo-root `.env`, defaulting to
`https://sarathi-api.niheshr.com`). Changing it later requires a frontend rebuild.

## 2. External prerequisites (do these first, they gate login and email)

- Google OAuth: in the Cloud console for the client, register the exact redirect
  URI `https://sarathi-api.niheshr.com/api/v1/auth/google/callback` and add
  `https://sarathi.niheshr.com` as an authorized JavaScript origin.
- AWS SES: verify the `niheshr.com` domain in `ap-south-1` and request production
  access (move out of the sandbox) so OTP/nudge email can go to arbitrary
  recipients, not just verified addresses.
- DNS: point `sarathi.niheshr.com` and `sarathi-api.niheshr.com` A/AAAA records at
  the host running the reverse proxy.

## 3. Deploy

```bash
# 1. Fill in the repo-root .env with the prod values from the table above.
$EDITOR .env

# 2. Build all images (backend build context = backend/, frontend = frontend/).
docker compose -f infra/docker-compose.prod.yml build

# 3. Bring the stack up. Postgres/Redis come up healthy, the `migrate` one-shot
#    runs `alembic upgrade head` and exits, then backend + worker + frontend start.
docker compose -f infra/docker-compose.prod.yml up -d

# 4. (First deploy only) seed the demo cohort into the running backend container.
docker compose -f infra/docker-compose.prod.yml run --rm migrate \
  python -m app.seed --cohort 20 --months 6 --seed 42

# 5. Point DNS + reverse proxy (section 4), then smoke-test.
```

Migrations run automatically on every `up` via the `migrate` service; there is no
manual migration step. To re-run them by hand:
`docker compose -f infra/docker-compose.prod.yml run --rm migrate alembic upgrade head`.

Logs: `docker compose -f infra/docker-compose.prod.yml logs -f backend worker`.

### Smoke test

```bash
# Local to the host (backend port is published on 8000):
curl -fsS http://127.0.0.1:8000/healthz
# {"status":"ok","db":true,"redis":true}

# Through the proxy once DNS + TLS are live:
curl -fsS https://sarathi-api.niheshr.com/healthz
```

`/healthz` returns 200 only when both Postgres and Redis are reachable, 503 otherwise.

## 4. Reverse proxy (TLS + SSE)

The backend streams `text/event-stream` for chat and the console live feed.
Response buffering MUST be disabled or the stream stalls. Both snippets below
front the two subdomains and keep SSE flowing.

### Caddy (automatic TLS)

Caddy provisions certificates automatically and needs `flush_interval -1` so SSE
responses are not buffered.

```caddy
sarathi.niheshr.com {
	reverse_proxy frontend:3000
}

sarathi-api.niheshr.com {
	reverse_proxy backend:8000 {
		flush_interval -1
	}
}
```

### nginx (TLS via certbot)

Obtain certs first, e.g.
`certbot --nginx -d sarathi.niheshr.com -d sarathi-api.niheshr.com`, then:

```nginx
server {
    listen 443 ssl;
    server_name sarathi.niheshr.com;
    # ssl_certificate / ssl_certificate_key managed by certbot

    location / {
        proxy_pass http://frontend:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}

server {
    listen 443 ssl;
    server_name sarathi-api.niheshr.com;
    # ssl_certificate / ssl_certificate_key managed by certbot

    location / {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE: never buffer or cache streamed responses.
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_set_header Connection '';
        proxy_set_header X-Accel-Buffering no;
    }
}

# Redirect http -> https (both hosts).
server {
    listen 80;
    server_name sarathi.niheshr.com sarathi-api.niheshr.com;
    return 301 https://$host$request_uri;
}
```

The backend already sets `--proxy-headers --forwarded-allow-ips=*`, so it trusts
the `X-Forwarded-*` headers from either proxy for correct scheme/host handling.

## 5. Notes

- Frontend build uses Turbopack (`next build --turbopack`, wired into
  `infra/Dockerfile.frontend`). The Webpack production build mis-splits the
  client-context modules when built on Linux, so every server-rendered route
  500s at runtime; Turbopack builds a correct standalone bundle. Always rebuild
  the frontend via the provided Dockerfile, not a hand-run `next build`.
- If you harden the Postgres password, change it in BOTH the `postgres` service
  env and the backend/worker/migrate `DATABASE_URL` (keep them in sync).
- The LangGraph checkpointer tables are created by the app on startup (not
  Alembic), so the first backend boot after a fresh DB may take a few extra
  seconds; the healthcheck `start-period` covers this.
- To publish nothing but the proxy, drop the `ports:` blocks on `backend` and
  `frontend` and put the proxy on the `sarathi` network instead.
