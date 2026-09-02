# Landing page + dashboard (Next.js, Arabic RTL)

- `/` public landing page. Copy lives in `content/landing.ar.json` and is linted by `pytest`
  (`tests/test_landing_copy.py`) so no advice language ships. Shows the latest published
  results from the API, counts a landing view via `POST /api/public/landing?ref=`.
- `/admin` dashboard v0: review queue with preview and editing, calendar, funnel with the paid
  preorder count against the target, job status. Asks for `LAB_ADMIN_TOKEN` once per tab.

```bash
cp .env.local.example .env.local   # API URL, checkout URL, displayed price
npm install
npm run dev                        # http://localhost:3000
```
