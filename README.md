# Trading Partner Data Collection Agent

An AI-native pipeline that automates structured data collection from trading partners for e-invoicing onboarding.

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Add your OpenAI key
cp .env.example .env
# edit .env and set OPENAI_API_KEY=sk-...

# 3. Run the full pipeline
python main.py
```

## What It Does

Given a CSV of trading partners with incomplete or messy data, the pipeline runs five stages end-to-end:

| Stage | What happens | Approach |
|---|---|---|
| 1. Load | Parse CSV, normalize column headers | Deterministic |
| 2. Validate | Detect missing/invalid fields per partner | Deterministic |
| 3. Outreach | Generate personalised email per partner | LLM (gpt-4o-mini) |
| 4. Load responses | Attach simulated free-text replies | — |
| 5. Parse + re-validate | Extract structured data from replies, re-check rules | LLM extract → Deterministic validate |

The final report shows each partner's resolution status and what (if anything) is still outstanding.

## Project Structure

```
trading_partner_agent/
├── main.py                     # Pipeline orchestrator
├── models.py                   # PartnerState dataclass + PartnerStatus enum
├── pipeline/
│   ├── loader.py               # CSV + response loading
│   ├── validator.py            # Deterministic field validation
│   ├── email_generator.py      # LLM outreach email generation
│   ├── response_parser.py      # LLM extraction + deterministic re-validation
│   └── report.py               # Terminal report
└── data/
    ├── partners.csv            # 5-row test input
    └── responses.json          # 4–5 simulated partner replies
```

## Design Decisions

### LLM vs Deterministic — the core question

The evaluation criterion the assignment calls out most explicitly is *where* you reach for an LLM versus deterministic code, and *why*.

**Deterministic everywhere it can be:**
- **TRN validation**: exactly 15 digits — pure regex `^\d{15}$`. An LLM here adds latency, cost, and non-determinism with zero accuracy benefit.
- **Peppol ID format**: `scheme:value` — same reasoning.
- **Address structure**: must contain comma-separated components (a structural heuristic). Not perfect globally, but predictable and free.
- **Gap detection**: null/empty checks. No ambiguity.
- **Post-extraction validation**: after the LLM extracts values from a free-text reply, the *same* deterministic rules run again. The LLM is never the last line of defence on data correctness.

**LLM where the input space is unbounded or requires natural language:**
- **Outreach email generation**: personalisation across varied partners, field-specific format guidance, polite tone. A template could approximate this but would produce robotic output for a first-impression vendor email.
- **Response parsing**: free-text replies are the canonical case for LLM use — varied formats, implicit references ("our scheme is 0088, value is 9876543"), non-standard labels ("VAT registration number" instead of "TRN"). A regex parser would be brittle; an LLM with a tight structured-output prompt handles ambiguity naturally.

### Column header normalisation

The current `COLUMN_ALIASES` dict in `loader.py` handles common variants deterministically and is the right call for a known or near-known schema.

**Limitation acknowledged:** In a production system ingesting CSVs from many different ERP or accounting systems, the input space becomes unbounded: `"Vndor Nme"`, `"Tax Reg. No."`, `"PEPPOL Network Identifier"`. A static alias dict cannot cover this. The right upgrade is a single cheap LLM call per CSV ingestion: send the raw headers and ask the model to map them to the canonical schema. The cost of one `gpt-4o-mini` call per upload is negligible compared to the cost of silently mapping the wrong column.

### State model

Each partner is a `PartnerState` dataclass that accumulates data through the pipeline stages. Status transitions are one-way and explicit (`PENDING → OUTREACH_READY → PARTIALLY_RESOLVED`, etc.). This makes the pipeline easy to reason about, test, and extend — you can inspect or persist state between any two stages.

### No agent framework

The pipeline is linear with clear stage boundaries. Introducing LangChain or LangGraph would add abstraction over a flow simple enough to read top-to-bottom in `main.py`. "Don't over-engineer" is explicit in the brief; a clean custom pipeline communicates the design more clearly than framework machinery.

## What I'd Improve with More Time

1. **Persistent state between runs** — write `PartnerState` to a JSON/SQLite store after each stage so the pipeline is resumable. In production, you'd generate and send emails in one run, then re-run days later once replies arrive.
2. **LLM column normalisation** — as described above, replace the alias dict with a one-shot LLM mapping step for truly unknown CSV schemas.
3. **Confidence scores on extraction** — prompt the response parser to return a confidence level per extracted field. Low-confidence extractions could be flagged for human review rather than silently accepted or rejected.
4. **Retry / follow-up generation** — for `PARTIALLY_RESOLVED` partners, generate a follow-up email requesting only the still-missing fields (the state model already supports this).
5. **Tests** — unit tests for all deterministic validators (fast, zero-cost, high value). Integration tests for the LLM stages would mock the OpenAI client.