# MALI MODE — FNB AOTY Hackathon 2026 MVP

MALI MODE is a working web application concept for youth entrepreneurs and small businesses. It helps users capture everyday business transactions, digitise existing records, and receive plain-language business insights based on saved activity. It is a real web app with a FastAPI backend and persistent database, not a static website.

## MVP features
- Account signup, email verification and sign-in with password hashing and signed HTTP-only session cookies.
- Role-specific profiles and dashboards for business owners, new entrepreneurs, suppliers and delivery partners.
- Guided startup business-plan draft and PDF download for new entrepreneurs.
- Transaction entry from natural-language text and supported browser speech-to-text. Users review extracted values before saving.
- Optional OCR scanning of paper records and receipts, with review before import.
- CSV import preview and explicit confirmation, designed to help users migrate existing records without retyping each row.
- Saved transaction history and user-specific business intelligence: recent sales, recorded costs, indicative balance, comparison to the previous 30-day period, largest cost category and repeat sale descriptions.
- Rule-based next-step advice derived only from that user's saved transaction records.
- Official links for government eTenders, the Central Supplier Database and SEDA.

## Business intelligence behaviour
The `/api/business-insights` endpoint calculates indicators from the signed-in user's saved records. It uses transparent rules, not a trained AI model. The interface explains that recommendations are indicative and only as complete as the records entered. The system does not claim to calculate audited profit, predict funding approval, process payments or verify suppliers.

## Deploy online with Supabase and Render

This app connects to Supabase through its PostgreSQL database using the FastAPI backend. The browser never receives database credentials.

1. Create a Supabase project. Open **Connect** and choose the **Session pooler** connection string. Keep the database password and URL private.
2. Push this folder to a **private GitHub repository**. Do not commit `.env` or real credentials.
3. In Render, choose **New → Blueprint** and select the repository containing `render.yaml`, or create a Web Service manually. The build command is `pip install -r requirements.txt`; the start command is `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
4. In Render's environment settings, set `DATABASE_URL` to the real Supabase PostgreSQL Session Pooler URL, `BASE_URL` to the deployed HTTPS Render URL, and configure `SECRET_KEY` with a strong random secret. Keep `COOKIE_SECURE=true` for HTTPS.
5. Configure SMTP variables so signup verification emails can be delivered. Without SMTP, verification links are only logged by the backend and are not suitable for a public demo.
6. Deploy and open `/health`. Create a test account, verify the email, save a transaction, refresh insights, and check that records persist after a redeploy.

The database module supports local SQLite and hosted PostgreSQL, normalizes a legacy `postgres://` URL, and requires TLS for PostgreSQL connections. The app creates its initial tables on startup. For production use, replace startup table creation with managed migrations before schema changes.

**Important:** Never put `DATABASE_URL`, `SECRET_KEY`, SMTP passwords, or the Supabase database password in frontend JavaScript or a public repository. Render free services may sleep when inactive, so the first request can take a little time to wake up. Test that separate accounts cannot see each other's records before sharing the demo.

## Run locally (Python 3.11+)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Generate a strong secret key and replace `SECRET_KEY` in `.env`. For a quick local demo, leave `COOKIE_SECURE=false` on localhost. Then run:

```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. API docs: http://127.0.0.1:8000/docs. Health check: http://127.0.0.1:8000/health. SQLite database `mali_mode.db` is created on first run.

## Email verification for local testing
Configure SMTP values in `.env` to send verification emails. If SMTP is not configured, the development verification link is logged in the server terminal; use this only for local testing. Do not deploy publicly with this development fallback.

## Optional scanning and voice
- Photo OCR requires Pillow, pytesseract and the Tesseract OCR executable installed on the host. Printed text generally works better than handwriting.
- Voice-to-text depends on browser/device support and may require microphone permission and HTTPS outside localhost. Typing and CSV import remain available when voice is unsupported.

## Sample CSV
Use `sample_transactions.csv` as an import example. The app previews rows before saving; check dates, amounts and transaction types before confirming.

## Security and limitations
This is a hackathon MVP, not a production-certified financial system. Before public deployment, configure HTTPS and secure cookies, add CSRF protection and rate limiting, add password reset and resend-verification flows, use database migrations, set up encrypted backups and monitoring, review POPIA obligations, and run a security test. Email verification verifies control of an email address only; it does not verify a person's identity or a supplier's legitimacy.

Supplier catalogues, real order fulfilment, verified supplier badges, delivery tracking, tender aggregation, payment processing, bank integrations and AI/LLM recommendations are not implemented as live integrations in this MVP. Official external links are provided as starting points only. Do not enter real payment card details or sensitive bank credentials.

## Hackathon demo path
1. Create a test account and verify it using the configured email or local terminal link.
2. Complete the profile and, for a new entrepreneur, review the generated business plan.
3. Record a sale and an expense using text; use voice if supported.
4. Import `sample_transactions.csv` or test a photo scan if OCR is installed.
5. Open Business Intelligence & Next Steps and show how recommendations respond to saved history.
6. Explain limitations honestly and show the security plan in the Sonke SSDLC submission.


## Transaction editing, duplicate protection and AI insights

- Saved transactions can be edited or deleted from the history table. Delete actions ask for confirmation; create/update/delete actions return clear status messages.
- Duplicate protection blocks a second record for the same user with the same date, type, amount and normalized description. Imports also skip matching duplicates. Similar-but-not-identical entries may still require human review.
- Raw text is kept in the transaction audit trail for natural-language creates/updates, alongside before/after snapshots. Audit events can be reviewed through `GET /api/transactions/audit`.
- To enable live AI explanations, set `OPENAI_API_KEY` and optionally `OPENAI_MODEL` in the deployment environment. Without a key or if the AI service fails, the app displays deterministic data-derived fallback analysis and identifies it as such. The app never fabricates customer preferences: ratings/feedback must be collected separately. Stock balance is only estimated from entered purchases and sales, not a physical stock count.
- New database tables are created automatically. Existing deployments should take a database backup before updating.

## Founder trade and formalisation upgrade

This update adds authenticated API workflows and dashboard panels for:

- Supplier listings and buyer order/quote requests (`GET/POST /api/suppliers`, `GET/POST /api/orders`, `PATCH /api/orders/{id}`). Supplier entries are user-entered pilot listings, not a verified live national marketplace. An order request is not a payment or confirmed purchase until supplier terms are accepted.
- Profile-aware document checklists (`GET /api/documents/checklist?kind=tender|fnb_business_account|funding|financial_records`). Requirements are general guidance; each bank, tender and funder notice is authoritative.
- Draft documents and downloadable PDFs (`POST /api/documents/generate`, `GET /api/documents/{id}/pdf`). Financial reports use the saved transaction ledger and are clearly labelled management drafts, not audited statements or tax-certified accounts.
- Tender/RFQ/funding notice analysis (`POST /api/documents/opportunity-review`). With `OPENAI_API_KEY` configured, the model extracts requirements from text the user provides. Without AI credentials, a transparent general fallback is returned. It does not fetch or invent live tender listings.

### Supabase schema

SQLAlchemy `Base.metadata.create_all()` creates missing tables when the app starts if the database role has permission. For a controlled Supabase deployment, inspect and run `supabase/migrations/20261017_founder_trade_formalisation.sql` in the Supabase SQL Editor before redeploying. Back up the database first. This migration only creates the new tables and indexes; it does not modify existing business data.

### Known limitations to test before production

- Supplier listings are not independently verified and supplier order requests require direct supplier confirmation.
- Actual checkout, payment-provider webhooks, invoice/payment allocations and supplier-side order acceptance are not implemented as a complete marketplace payment system.
- Tender listings are not automatically discovered. Users must paste an official opportunity notice for tailored requirement extraction.
- Generated documents are drafts. Reconcile source records and confirm the bank/tender/funder's current requirements before submission.
