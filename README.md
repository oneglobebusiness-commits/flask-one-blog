# Blog Studio (Flask)

One Flask app that replaces the old Next.js frontend (`Blog1`) and NestJS backend (`One-Blog-Final`).
It serves the pages (HTML, CSS, plain JavaScript) and the API from the same server.
It uses the same MongoDB collections and the same `/api/v1/...` paths, so existing data keeps working.

## Run it

Use Python 3.11 or newer in production (3.9 works, but is past end of life).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then fill in the values
.venv/bin/python run.py     # http://localhost:5000
```

Production: `gunicorn run:app --workers 1 --threads 8 --timeout 300` (also in `Procfile`).
Keep one worker: rate limits are held in memory, and the scheduler runs inside the app.

## Settings to carry over

Copy `MONGO_URI`, `JWT_SECRET` and the `SHOPIFY_*` values from the old backend's `.env`.
Keep the same database name. If `MONGO_URI` has no database name, the old app used `test`, which is
the default for `MONGO_DB` here too.

Set `ADMIN_PASSWORD` too. On startup it replaces the old hardcoded admin password, and that password
is refused at login until then.

In the Shopify Partner dashboard, point the App URL at this server and the redirect URL at
`https://<your-domain>/api/v1/integrations/shopify/callback`.

The Gemini key still comes from the `ai_providers` collection.

## Layout

```
app/api/        routes: accounts.py (login, install, plans), content.py (blogs, publishing), store.py
app/services/   logic: ai, blogs, publishing, shopify, subscriptions, intelligence, jobs, storage
app/prompts/    the AI prompts for blogs and campaigns
app/templates/  HTML pages
app/static/     CSS, JavaScript and images
tests/          run with: pip install -r requirements-dev.txt && pytest
uploads/        generated hero images (needs a persistent disk)
```
# 1-blog-flask-tech
