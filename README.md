# LifePilot

**Turn paperwork into a plan.** LifePilot reads bills, receipts, warranties, rental agreements, certificates and application forms, extracts the fields that matter, and turns them into deadlines, tasks and calendar reminders — all on your own machine.

Built with **Streamlit · SQLAlchemy (SQLite/PostgreSQL) · pdfplumber + Tesseract OCR · spaCy · pandas/Plotly · APScheduler · icalendar**.

---

## Screenshots

| Dashboard | Upload |
| --- | --- |
| ![Dashboard](docs/screenshots/dashboard.png) | ![Upload](docs/screenshots/upload.png) |

| Documents | Document detail |
| --- | --- |
| ![Documents](docs/screenshots/documents.png) | ![Document detail](docs/screenshots/document-detail.png) |

| Reminders & calendar | Spending |
| --- | --- |
| ![Reminders](docs/screenshots/reminders.png) | ![Spending](docs/screenshots/spending.png) |

> Screenshots were captured from the bundled sample documents. Regenerate them any time by loading the samples and using your OS screenshot tool.

---

## What it does

1. **Read** — extracts text from text PDFs with `pdfplumber`; falls back to Tesseract OCR for scans and photos.
2. **Understand** — classifies the document and pulls out fields (vendor, amount, dates, parties, reference numbers, required documents) with per-field confidence.
3. **Review** — anything below **60% confidence** is flagged *needs review*. Edit the value once and it is stored at 100% confidence.
4. **Act** — generates document-specific tasks and deadlines, then shows a 7-day banner on the dashboard.
5. **Remind** — an in-app APScheduler job creates deduplicated notifications; optional SMTP email digests.
6. **Export** — downloads an `.ics` calendar for all deadlines or a single document.

### Task rules

| Document | Trigger | Generated action |
| --- | --- | --- |
| Bill / receipt | amount + due date | `Pay Rs.X to <vendor> by <date>` |
| Warranty | expiry date | Reminder **30 days** before expiry |
| Agreement | renewal date | `Review renewal` **15 days** before |
| Application | required documents / missing fields | `Collect document: …` task per item + missing-info flags |
| Certificate | expiry date | Renewal reminder before expiry |
| Any | dated obligation clause | Follow-up task from the clause |

### Confidence & review

- Every stored field has `confidence` (0–1) and a `source` (`rule`, `heuristic`, `user`, `llm`).
- Values below `0.60` are highlighted and listed in **Needs review**.
- Confirming or editing a value sets `confidence = 1.0`, `source = user`, and resolves the matching missing-info row.

### Optional AI assist (off by default)

When enabled **and** an API key is configured, the pipeline calls an OpenAI-compatible chat-completions endpoint **only** for expected fields that are missing or below 60% confidence. Responses must be strict JSON and are schema-validated with Pydantic before anything is saved. No text leaves your machine while the toggle is off, and nothing is sent during sample loading.

---

## Project structure

```
lifepilot/
├─ app.py                     # Streamlit UI (dashboard, upload, documents, reminders, spending, settings)
├─ config.py                  # env-driven settings, paths, thresholds
├─ scheduler.py               # reminder checks + APScheduler singleton
├─ notifications.py           # optional SMTP delivery
├─ seed.py                    # one-click bundled sample documents
├─ utils.py                   # money/date formatting, category inference
├─ pipeline/
│  ├─ ocr.py                  # pdfplumber + Tesseract/pdf2image
│  ├─ classify.py             # rule-based document type detection
│  ├─ extract.py              # fields, dates, amounts, NER + confidence
│  ├─ obligations.py          # dated obligation clauses
│  ├─ confidence.py           # scoring helpers
│  ├─ tasks.py                # expected fields, deadlines, tasks, missing info
│  ├─ llm_fallback.py         # optional, schema-validated LLM extraction
│  └─ processor.py            # orchestration + save_upload
├─ db/
│  ├─ models.py               # documents, entities, deadlines, tasks, missing_info, settings, notifications
│  ├─ database.py             # engine/session singleton
│  └─ crud.py                 # all queries
├─ exports/
│  └─ calendar.py             # .ics builder
├─ tests/
│  ├─ sample_documents/       # 4 bundled PDFs + .txt twins
│  ├─ make_samples.py         # regenerates the samples (reportlab)
│  └─ test_*.py               # 75 unit tests
├─ docs/screenshots/
├─ .streamlit/config.toml
├─ .env.example
├─ requirements.txt
└─ README.md
```

### Database tables

| Table | Purpose |
| --- | --- |
| `documents` | one row per upload: filename, stored path, type, raw text, status, timestamps |
| `entities` | extracted fields (`field_name`, `value`, `value_type`, `confidence`, `source`, `confirmed`) |
| `deadlines` | dated obligations (`due_date`, `kind`, `remind_days_before`, `status`) |
| `tasks` | actionable items linked to a document and optionally a deadline |
| `missing_info` | expected fields that could not be found |
| `app_settings` | single row: currency, reminder default, LLM/email toggles |
| `notifications` | deduplicated in-app reminders created by the scheduler |

All child tables cascade from `documents`. The schema uses portable SQLAlchemy types only — switching to PostgreSQL is just a connection-string change.

---

## Setup

### 1. Requirements

- Python **3.11+**
- Tesseract OCR and Poppler (only needed for scanned PDFs/images — text PDFs work without them)

### 2. Create a virtual environment

Windows PowerShell:

```powershell
cd lifepilot
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

macOS / Linux:

```bash
cd lifepilot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Install Tesseract (OCR)

**Windows** — install the UB-Mannheim build from <https://github.com/UB-Mannheim/tesseract/wiki>, tick **Add to PATH**, or point LifePilot at the binary:

```env
LIFEPILOT_TESSERACT_CMD=C:/Program Files/Tesseract-OCR/tesseract.exe
```

**macOS**

```bash
brew install tesseract
```

**Ubuntu / Debian**

```bash
sudo apt update && sudo apt install tesseract-ocr
```

### 4. Install Poppler (needed to rasterise scanned PDFs)

**Windows** — download a build from <https://github.com/oschwartz10612/poppler-windows/releases>, extract it, then either add `...\poppler\Library\bin` to `PATH` or set:

```env
LIFEPILOT_POPPLER_PATH=C:/tools/poppler/Library/bin
```

**macOS**

```bash
brew install poppler
```

**Ubuntu / Debian**

```bash
sudo apt install poppler-utils
```

LifePilot detects missing binaries and shows a clear warning instead of crashing. Text-based PDFs and `.txt` files work with no OCR setup at all.

### 5. Optional spaCy model

Named-entity extraction uses `en_core_web_sm` when present and degrades to a deterministic regex/heuristic fallback when it is not.

```bash
python -m spacy download en_core_web_sm
```

### 6. Configuration

Copy `.env.example` to `.env` and edit only what you need:

```powershell
Copy-Item .env.example .env
```

Everything is optional. Defaults: SQLite at `lifepilot/data/lifepilot.db`, uploads at `lifepilot/data/uploads`, currency INR, reminders every 6 hours.

### 7. Run

From the `lifepilot/` folder (recommended, so `.streamlit/config.toml` is picked up):

```bash
streamlit run app.py
```

Or from the folder that contains `lifepilot/`:

```bash
streamlit run lifepilot/app.py
```

The app opens at <http://localhost:8501>.

### 8. Load sample documents

Click **✨ Load 4 sample documents** on the empty dashboard, or from Settings → *Load sample documents*. The samples are:

| File | Type | Highlights |
| --- | --- | --- |
| `electricity_bill.pdf` | Bill | ₹2,158.75 due 06 Nov 2026, vendor, account number |
| `warranty_card.pdf` | Warranty | 24-month warranty expiring 11 Aug 2028 |
| `rental_agreement.pdf` | Agreement | ₹28,000 rent, ₹1,12,000 deposit, renewal 15 Apr 2027 |
| `application_form.pdf` | Application | submission 30 Nov 2026, 5 required documents |

To upload your own, open **Upload**, choose PDF/JPG/PNG files (25 MB each), and press **Process documents**.

---

## Configuration reference

All variables are read from the environment or `lifepilot/.env`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `LIFEPILOT_DATA_DIR` | `lifepilot/data` | database + uploads folder |
| `LIFEPILOT_DB_URL` | `sqlite:///…/data/lifepilot.db` | any SQLAlchemy URL, e.g. PostgreSQL |
| `LIFEPILOT_TESSERACT_CMD` | — | path to the Tesseract binary |
| `LIFEPILOT_POPPLER_PATH` | — | path to the Poppler `bin` folder |
| `LIFEPILOT_REMINDER_CHECK_HOURS` | `6` | scheduler interval |
| `LIFEPILOT_LLM_API_KEY` | — | enables AI assist in Settings |
| `LIFEPILOT_LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `LIFEPILOT_LLM_MODEL` | `gpt-4o-mini` | model used for fallback |
| `LIFEPILOT_LLM_TIMEOUT` | `45` | request timeout (seconds) |
| `LIFEPILOT_SMTP_HOST` / `_PORT` | — / `587` | SMTP server |
| `LIFEPILOT_SMTP_USER` / `_PASSWORD` | — | SMTP credentials |
| `LIFEPILOT_SMTP_FROM` | `SMTP_USER` | sender address |
| `LIFEPILOT_SMTP_USE_TLS` | `true` | STARTTLS |
| `LIFEPILOT_SMTP_*` + recipient | — | recipient is set in **Settings → Email** |

### PostgreSQL

```env
LIFEPILOT_DB_URL=postgresql+psycopg://lifepilot:secret@localhost:5432/lifepilot
```

Install a driver (`pip install "psycopg[binary]"`), start PostgreSQL, and run the app — `init_db()` creates the tables on first launch.

### Email reminders

Set the SMTP variables, restart, then enable **Email me reminder digests** and enter a recipient in **Settings → Email**. A digest is sent only when the scheduler (or **Run reminder check now**) creates new reminders.

---

## How it works

```
upload → extract_text → classify_document → extract_entities → extract_obligations
       → derive_deadlines → generate_tasks → detect_missing_info → store
```

Each step is a separate function in `pipeline/`; `pipeline/processor.py` wires them together and records failures on the document row instead of raising into the UI.

- **Classification** is keyword/weight based (vendor names, GST/invoice words, "warranty", "lease", "application form", …) with a filename hint when the text is ambiguous.
- **Extraction** combines labelled regexes, date/amount parsing (`dateparser`, Indian grouping, lakh/crore) and spaCy entities, and scores each field. A value found by multiple independent patterns scores higher.
- **Deadlines** come from document dates plus obligation clauses ("payment due within 15 days"), anchored to the document's own date when possible.
- **Missing info** compares extracted fields against the expected-field list for the detected type.

### Privacy

- Files are stored under `lifepilot/data/uploads`; extracted text and fields live in the local database.
- OCR runs locally through Tesseract. There is no cloud OCR.
- AI assist is opt-in, runs only for missing/low-confidence fields, and can be turned off at any time.
- `.ics` files are generated locally; importing them into Google Calendar/Outlook is your choice.

---

## Tests

The suite covers extraction, classification, confidence scoring, obligation parsing, task/deadline generation, LLM schema validation, calendar export, the end-to-end pipeline and the scheduler.

Run from the folder that contains `lifepilot/`:

```bash
python -m pytest lifepilot/tests -q
```

Expected: **75 passed**. Tests use an in-memory SQLite database and the bundled `.txt`/PDF samples, so no network, OCR or API key is required.

Regenerate the sample PDFs (requires `reportlab`):

```bash
python -m lifepilot.tests.make_samples
```

---

## Deploy a public demo (Streamlit Community Cloud)

The repository is already prepared for a free public deployment: `app.py` is at the root, `requirements.txt` and `packages.txt` install Python and OCR dependencies, and **demo mode** auto-loads the samples so visitors land on a populated dashboard.

### 1. Push the project to GitHub

Create an empty **public** repository at <https://github.com/new> (no README, no .gitignore), then from the `lifepilot/` folder:

```powershell
git init -b main
git add .
git commit -m "LifePilot: document-to-action assistant"
git remote add origin https://github.com/<your-username>/lifepilot.git
git push -u origin main
```

`data/`, `.env` and `.streamlit/secrets.toml` are git-ignored, so your local database and secrets are never published.

### 2. Create the app

1. Go to <https://share.streamlit.io> and sign in with GitHub.
2. Click **Create app** → **Deploy a public app from GitHub**.
3. Repository: `<your-username>/lifepilot`, branch: `main`, main file path: `app.py`.
4. Open **Advanced settings**:
   - **Python version:** 3.12
   - **Secrets** (paste this TOML):

     ```toml
     LIFEPILOT_DEMO_MODE = "true"
     ```

5. Click **Deploy**. The first build takes a few minutes (spaCy is the slowest dependency).

Your app is live at `https://<app-name>.streamlit.app` — that is the link to put on your resume. Each push to `main` redeploys automatically.

### What demo mode does

- Loads the four bundled sample documents on first launch, so the dashboard is never empty.
- Disables **Clear all documents** / bulk deletion.
- Keeps AI assist and email off (no API key or SMTP credentials are exposed).
- Adds a visible notice asking visitors not to upload personal documents.

The public filesystem is ephemeral: the SQLite database and uploaded files reset when Streamlit restarts or redeploys the app. That is fine for a portfolio demo and avoids accumulating visitors' data.

`packages.txt` installs `tesseract-ocr`, `tesseract-ocr-eng` and `poppler-utils` on the Linux host, so scanned PDFs and images also get OCR in the deployed app.

### Optional: a custom URL / other hosts

- Streamlit Cloud allows a custom subdomain in **App settings → General**.
- The same repo runs on **Render**, **Railway**, **Fly.io** or **Hugging Face Spaces** if you prefer their free tiers; set `LIFEPILOT_DEMO_MODE=true` as an environment variable and keep `packages.txt`/system packages available for OCR. For PostgreSQL hosting, set `LIFEPILOT_DB_URL`; the schema is portable.
- If you enable AI assist publicly, set a spending limit on your LLM API key — strangers can trigger calls.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| *Tesseract not found* in the sidebar | Install Tesseract and add it to `PATH`, or set `LIFEPILOT_TESSERACT_CMD`. |
| *The PDF appears to be scanned…* | Install Tesseract **and** Poppler (or set `LIFEPILOT_POPPLER_PATH`). |
| `spacy` model warning | `python -m spacy download en_core_web_sm`; heuristics still work without it. |
| No reminders appear | The deadline must be inside its reminder window; press **Run reminder check now** on the Reminders page. |
| Emails not sent | SMTP variables must be set, the recipient saved in Settings, and a *new* reminder created. |
| `ModuleNotFoundError: lifepilot` | Run Streamlit from inside `lifepilot/` (or from its parent) and run pytest from the parent folder. |
| Upload rejected | Default limit is 25 MB per file (`config.MAX_UPLOAD_MB` / `.streamlit/config.toml`). |

### Known limitations

- OCR quality depends on scan quality; handwriting is not supported.
- Field extraction is optimised for English documents and Indian/UK/US date formats.
- The spending dashboard treats amounts as recorded and does not convert currencies.
- The scheduler runs inside the Streamlit process, so reminders only fire while the app is running.

---

## Roadmap ideas

- Multi-user accounts and per-user databases
- Bank-statement import and recurring-bill detection
- Push notifications / WhatsApp reminders
- Learned extraction models with active learning from confirmed fields
