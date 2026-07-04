# TermsGrader

Nobody reads Terms of Service. Not because people are lazy, but because the documents are deliberately written to not be read. TermsGrader is a GenLayer Intelligent Contract that grades any legal document across four consumer-protection dimensions and writes the verdict on-chain permanently.

Paste a ToS, privacy policy, employment contract, or rental agreement. Get back letter grades with plain-English explanations. The result is timestamped and tamper-proof — proof of what those terms said on the exact date you checked, before you signed anything.

---

## What it grades

Four dimensions, each scored A (user-friendly) through F (dangerous or deceptive):

**DATA_RIGHTS** — what the company can actually do with personal data. Collection, sharing, selling, retention periods, deletion rights. An A means the user owns their data and explicit consent is required for every use. An F means data gets sold to unspecified third parties with no deletion option.

**CANCELLATION** — how hard it is to leave. Cancel-anytime with instant effect and a pro-rata refund is an A. No cancellation, no refund, 90-day account closure is an F.

**LIABILITY** — what the company escapes and what the user gives up. This is where mandatory arbitration clauses, class action waivers, and "as-is" disclaimers land.

**HIDDEN** — anything that deviates significantly from what a reasonable person signing up for that type of service would expect. Not illegal, necessarily. Just buried.

The contract computes an overall grade as a weighted floor of the four dimensions — intentionally pessimistic, because a document with one F should drag the overall grade down.

---

## How consensus works

Each call to `grade_document` runs through `gl.eq_principle.prompt_non_comparative`. Multiple GenLayer validators independently grade the submitted document and must reach consensus before anything gets written on-chain.

The equivalence check is specific: validators don't need identical wording, but they must agree on the same letter grade per dimension within one grade tolerance. A validator giving C and another giving D counts as agreement. C and A doesn't. This isn't just "return valid JSON" — it's substantive agreement on a legal judgment.

Where validators genuinely can't agree on a dimension (because the clause language is ambiguous enough that reasonable readers disagree by more than one grade), that dimension gets flagged `"disputed": true`. Deliberately obscure legal language produces a DISPUTED flag rather than a silently forced average. That flag is itself useful information.

---

## State design

Each submission stores:

```python
{
  "id":              "TG000001",
  "submitter":       "0x...",          # wallet address
  "document_title":  "Spotify ToS",
  "document_hash":   "a3f9b2c1...",    # rolling hash of the exact submitted text
  "char_count":      4821,
  "status":          "graded",
  "grades": {
    "data_rights":  { "grade": "D", "explanation": "...", "confidence": "HIGH", "disputed": false },
    "cancellation": { "grade": "B", "explanation": "...", "confidence": "MEDIUM", "disputed": false },
    "liability":    { "grade": "F", "explanation": "...", "confidence": "HIGH", "disputed": false },
    "hidden":       { "grade": "C", "explanation": "...", "confidence": "LOW", "disputed": true }
  },
  "overall_grade":   "D",
  "overall_summary": "...",
  "block_number":    42
}
```

The `document_hash` field ties the on-chain grade to the exact text submitted. If the document changes and gets re-graded, the hash won't match the previous submission — you can prove the grade applies to a specific version, not a later edited one.

---

## Methods

### Write

**`grade_document(submitter_address, document_title, document_text)`**

Submits a document for grading. Runs the full AI consensus evaluation and writes the result on-chain. Returns a submission ID like `TG000001`, or one of two error sentinels: `ERROR_EMPTY_TITLE` or `ERROR_EMPTY_TEXT` (triggers if the document is under 100 characters — too short to grade meaningfully).

The document text is capped at 6000 characters sent to the AI. Longer documents get graded on their first 6000 characters, and the summary will note if the document appeared truncated.

### Read (all free, no gas)

**`get_submission(submission_id)`** — full result by ID, including all dimension grades, explanations, confidence levels, disputed flags, and overall summary.

**`get_my_submissions(address)`** — all submissions from a wallet address, most recent first.

**`get_submission_by_hash(document_hash)`** — check if a specific document version was already graded without re-submitting. Useful for callers who want to avoid duplicate grading fees.

**`get_recent_submissions(limit)`** — anonymous public feed of recent grades (no submitter address). Returns title, grades per dimension, overall, and summary. Limit is a string, clamped to 1-50.

**`get_stats()`** — aggregate grade distributions across all submissions, broken down by dimension and overall. Designed for builders who want to build dashboards, comparison tools, or consumer-watchdog apps on top of this contract.

---

## Building on top of this

`get_stats()` returns grade distribution data across every graded document. A browser extension could auto-submit ToS pages and display the grade inline before signup. A watchdog dashboard could track how specific companies' terms change over time. The on-chain record makes both of those possible without trusting a centralised database.

The `document_hash` + `block_number` combination gives any downstream tool a permanent, verifiable reference to the exact version of a document that was graded.

---

## Deployed on

GenLayer studionet. Contract address: see the GenLayer Explorer link in the submission evidence.

---

## Running locally

No local setup needed beyond GenLayer Studio. Deploy `termsgrader.py` to studionet, call `grade_document` with any plain-text legal document, and read the result via `get_submission`.

The contract has no external dependencies beyond the GenLayer SDK.
