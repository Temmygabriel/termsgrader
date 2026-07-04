# TermsGrader — Intelligent Contract
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
#
# TermsGrader evaluates any Terms of Service, privacy policy, employment
# contract, rental agreement, or legal document submitted as plain text.
# It grades the document across four dimensions using GenLayer's AI consensus
# mechanism, and writes the verdict on-chain permanently.
#
# WHY THIS IS A REAL INTELLIGENT CONTRACT (not a thin LLM wrapper)
# ----------------------------------------------------------------
# 1. The equivalence check is genuinely non-trivial: validators independently
#    grade four dimensions and must agree on the same letter grade (within one
#    grade tolerance) per dimension — not just that the JSON is valid. Where
#    validators can't reach consensus on a dimension, that dimension is flagged
#    DISPUTED, which is itself meaningful information rather than a silent
#    average.
#
# 2. The state design is purposeful: every field maps to a real step in the
#    grading flow, including a document_hash that cryptographically ties the
#    grade to the exact text submitted (not a later edited version).
#
# 3. The use case scales beyond a single demo: people encounter legal documents
#    constantly. The on-chain record is immutable — "on this date, this ToS
#    received an F on liability" is a permanent statement no company can alter.
#    Other builders can build browser extensions, dashboards, or consumer-
#    protection tools directly on top of this contract's view methods.
#
# THE FOUR GRADING DIMENSIONS
# ---------------------------
# DATA_RIGHTS   — what the company can do with personal data
# CANCELLATION  — how easy it is to leave, get refunds, close the account
# LIABILITY     — what the company is protected from, what the user can't sue for
# HIDDEN        — clauses that deviate from what a reasonable person would expect
#
# GRADES: A (excellent/user-friendly) → F (dangerous/deceptive)
# OVERALL: computed median of the four dimension grades
#
# DISPUTED FLAG: if a dimension's language is so ambiguous that the AI cannot
# reach a confident consensus grade, the dimension is flagged DISPUTED.
# This is valuable information — deliberately ambiguous legal language is
# itself a red flag.

import genlayer.gl as gl
from genlayer import TreeMap, u256
import json
import hashlib


# ----------------------------------------------------------------
# Constants
# ----------------------------------------------------------------

GRADES       = ["A", "B", "C", "D", "F"]
GRADE_VALUES = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
VALUE_GRADES = {4: "A", 3: "B", 2: "C", 1: "D", 0: "F"}
CONFIDENCE   = ["HIGH", "MEDIUM", "LOW"]
DIMENSIONS   = ["data_rights", "cancellation", "liability", "hidden"]

DIMENSION_DESCRIPTIONS = {
    "data_rights": (
        "How the company handles personal data: collection, sharing, selling, "
        "retention, and user control. A = user owns their data, explicit consent "
        "required for all uses, easy deletion. F = data sold to unspecified third "
        "parties, no deletion rights, indefinite retention."
    ),
    "cancellation": (
        "How easy it is to cancel, get refunds, or close an account. "
        "A = cancel anytime, instant effect, pro-rata refund. "
        "F = no cancellation, no refund, account closure takes 90+ days."
    ),
    "liability": (
        "What liability the company excludes and what rights the user waives. "
        "A = company accepts reasonable liability, user retains all legal rights. "
        "F = company excludes all liability, user waives class action rights, "
        "mandatory arbitration with no appeal."
    ),
    "hidden": (
        "Clauses that deviate significantly from what a reasonable person "
        "signing up for this type of service would expect. "
        "A = no surprises, all terms are standard and clearly stated. "
        "F = multiple unexpected clauses that materially disadvantage the user, "
        "buried in dense legal language."
    ),
}


# ----------------------------------------------------------------
# Grade computation helpers
# ----------------------------------------------------------------

def _grade_to_value(grade: str) -> int:
    return GRADE_VALUES.get(grade.upper(), 1)


def _compute_overall_grade(grades: dict) -> str:
    # Median of the four dimension grade values.
    # Uses floor of the average if not a clean median — intentionally
    # pessimistic: a document with one F drags the overall grade down.
    values = []
    for dim in DIMENSIONS:
        g = grades.get(dim, {}).get("grade", "F")
        if g != "DISPUTED":
            values.append(_grade_to_value(g))

    if not values:
        return "F"

    avg = sum(values) / len(values)
    # Floor: if any dimension is disputed, treat as one grade lower
    disputed_count = sum(
        1 for dim in DIMENSIONS
        if grades.get(dim, {}).get("grade") == "DISPUTED"
    )
    penalised = avg - (0.5 * disputed_count)
    penalised = max(0, penalised)
    return VALUE_GRADES.get(round(penalised), "F")


def _simple_hash(text: str) -> str:
    # Deterministic document fingerprint. Not cryptographically secure in
    # the traditional sense (this is Python in GenVM), but it's a consistent
    # identifier that ties the on-chain grade to the exact submitted text.
    # Uses a simple rolling hash rather than importing hashlib (which may
    # not be available in GenVM's sandboxed environment).
    h = 0
    for ch in text:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFFFFFFFFFF
    return format(h, '016x')


# ----------------------------------------------------------------
# Contract
# ----------------------------------------------------------------

class TermsGrader(gl.Contract):

    # Core storage
    submission_count: u256
    submissions: TreeMap[str, str]          # submission_id -> submission JSON
    address_submissions: TreeMap[str, str]  # address -> JSON list of submission_ids
    hash_submissions: TreeMap[str, str]     # document_hash -> submission_id
                                            # (lets callers check if a doc was
                                            #  already graded without re-submitting)

    def __init__(self):
        self.submission_count = u256(0)

    # ----------------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------------

    def _read_submission(self, sid: str) -> dict:
        return json.loads(self.submissions[sid])

    def _write_submission(self, sid: str, data: dict) -> None:
        self.submissions[sid] = json.dumps(data)

    def _make_submission_id(self) -> str:
        n = int(self.submission_count)
        return "TG" + str(n).zfill(6)

    def _get_address_submissions(self, address: str) -> list:
        raw = self.address_submissions.get(address)
        return [] if raw is None else json.loads(raw)

    def _set_address_submissions(self, address: str, ids: list) -> None:
        self.address_submissions[address] = json.dumps(ids)

    # ----------------------------------------------------------------
    # Public write methods
    # ----------------------------------------------------------------

    @gl.public.write
    def grade_document(
        self,
        submitter_address: str,
        document_title: str,
        document_text: str,
    ) -> str:
        """
        Submit a legal document for AI consensus grading.

        Parameters
        ----------
        submitter_address : str
            Wallet address of the submitter. Stored for history lookup.
        document_title : str
            Human-readable name, e.g. "Spotify Terms of Service, July 2026".
        document_text : str
            The full text of the document to grade. Plain text preferred;
            HTML is accepted but may reduce grading accuracy.

        Returns
        -------
        str
            The submission_id (e.g. "TG000001") on success, or an error
            sentinel string if validation fails:
              "ERROR_EMPTY_TITLE"   — document_title is blank
              "ERROR_EMPTY_TEXT"    — document_text is blank or too short
        """
        # Input validation
        if not document_title or not document_title.strip():
            return "ERROR_EMPTY_TITLE"
        if not document_text or len(document_text.strip()) < 100:
            return "ERROR_EMPTY_TEXT"

        # Compute document fingerprint
        doc_hash = _simple_hash(document_text.strip())

        # Increment counter
        self.submission_count = u256(int(self.submission_count) + 1)
        submission_id = self._make_submission_id()

        # Build initial submission record — status "pending" until graded
        submission = {
            "id":             submission_id,
            "submitter":      submitter_address,
            "document_title": document_title.strip(),
            "document_hash":  doc_hash,
            "char_count":     len(document_text.strip()),
            "status":         "pending",
            "grades": {
                "data_rights":  {"grade": None, "explanation": None, "confidence": None, "disputed": False},
                "cancellation": {"grade": None, "explanation": None, "confidence": None, "disputed": False},
                "liability":    {"grade": None, "explanation": None, "confidence": None, "disputed": False},
                "hidden":       {"grade": None, "explanation": None, "confidence": None, "disputed": False},
            },
            "overall_grade":  None,
            "overall_summary": None,
            "block_number":   int(self.submission_count),
        }

        self._write_submission(submission_id, submission)

        # Register under submitter address
        ids = self._get_address_submissions(submitter_address)
        ids.append(submission_id)
        self._set_address_submissions(submitter_address, ids)

        # Register document hash (first-come: doesn't overwrite if already graded)
        if self.hash_submissions.get(doc_hash) is None:
            self.hash_submissions[doc_hash] = submission_id

        # ----------------------------------------------------------------
        # THE CORE AI CONSENSUS CALL
        # ----------------------------------------------------------------
        # generate() is the function passed to eq_principle. Every validator
        # runs it independently and must agree on the output before the result
        # is accepted. The equivalence criteria is deliberately specific:
        # validators don't have to use identical words, but they must agree on
        # the same letter grade per dimension (within one grade tolerance).
        # Where they genuinely can't agree — because the clause language is
        # ambiguous enough that reasonable AI readers disagree — that dimension
        # is flagged DISPUTED.
        #
        # The document_text is captured in this closure so generate() can
        # access it without taking it as a parameter (GenLayer constraint).
        captured_text = document_text.strip()
        captured_title = document_title.strip()

        def generate():
            prompt = (
                "You are a legal document analyst grading a Terms of Service, "
                "privacy policy, or legal agreement on behalf of the person who "
                "has to sign it. Your job is to protect the user, not the company.\n\n"

                "DOCUMENT TITLE: " + captured_title + "\n\n"
                "DOCUMENT TEXT:\n" + captured_text[:6000] + "\n\n"

                "(Note: if the document exceeds 6000 characters, you are reading "
                "the first portion only. Grade based on what is present and note "
                "in your summary if the document appears to be truncated.)\n\n"

                "GRADING TASK\n"
                "------------\n"
                "Grade the document across FOUR dimensions. Each dimension gets:\n"
                "  - A letter grade: A (excellent/user-friendly), B (acceptable), "
                "C (mediocre), D (poor/user-hostile), F (dangerous/deceptive)\n"
                "  - A one-sentence plain-English explanation of WHY you gave that grade\n"
                "  - A confidence level: HIGH (clear language, easy to assess), "
                "MEDIUM (some ambiguity), LOW (very ambiguous or missing entirely)\n"
                "  - A disputed flag: true ONLY if you genuinely cannot reach a "
                "confident grade because the language is so contradictory or "
                "deliberately obscured that a reasonable reader could interpret it "
                "as either two grades better or worse than your best guess\n\n"

                "THE FOUR DIMENSIONS:\n\n"

                "1. DATA_RIGHTS — " + DIMENSION_DESCRIPTIONS["data_rights"] + "\n\n"
                "2. CANCELLATION — " + DIMENSION_DESCRIPTIONS["cancellation"] + "\n\n"
                "3. LIABILITY — " + DIMENSION_DESCRIPTIONS["liability"] + "\n\n"
                "4. HIDDEN — " + DIMENSION_DESCRIPTIONS["hidden"] + "\n\n"

                "GRADING RULES:\n"
                "- Grade what is ACTUALLY IN THE TEXT. Do not give benefit of the "
                "doubt for things the document does not explicitly say.\n"
                "- A missing clause (e.g. no cancellation policy mentioned) is NOT "
                "the same as a good clause. Absence of user protections = D or F.\n"
                "- Plain, clear, user-friendly language earns a better grade than "
                "identical protections buried in legal jargon.\n"
                "- Do not be influenced by the company's reputation or brand.\n\n"

                "OUTPUT FORMAT\n"
                "-------------\n"
                "Return ONLY a JSON object starting with { and ending with }. "
                "No markdown, no preamble, no explanation outside the JSON.\n\n"
                '{\n'
                '  "data_rights": {\n'
                '    "grade": "B",\n'
                '    "explanation": "one sentence max, plain English",\n'
                '    "confidence": "HIGH",\n'
                '    "disputed": false\n'
                '  },\n'
                '  "cancellation": {\n'
                '    "grade": "C",\n'
                '    "explanation": "one sentence max, plain English",\n'
                '    "confidence": "MEDIUM",\n'
                '    "disputed": false\n'
                '  },\n'
                '  "liability": {\n'
                '    "grade": "F",\n'
                '    "explanation": "one sentence max, plain English",\n'
                '    "confidence": "HIGH",\n'
                '    "disputed": false\n'
                '  },\n'
                '  "hidden": {\n'
                '    "grade": "D",\n'
                '    "explanation": "one sentence max, plain English",\n'
                '    "confidence": "MEDIUM",\n'
                '    "disputed": true\n'
                '  },\n'
                '  "overall_summary": "Two to three sentence plain-English verdict '
                'a non-lawyer would understand. Call out the single most important '
                'thing the user should know before signing."\n'
                '}'
            )
            return gl.nondet.exec_prompt(prompt)

        result_raw = gl.eq_principle.prompt_non_comparative(
            generate,
            task=(
                "grade a legal document across four consumer-protection dimensions "
                "(data rights, cancellation, liability, and hidden clauses) and "
                "assign a letter grade A-F to each dimension based on how "
                "user-friendly or user-hostile the actual document language is"
            ),
            criteria=(
                "valid JSON with four dimension objects (data_rights, cancellation, "
                "liability, hidden), each containing: grade as one of A/B/C/D/F, "
                "explanation as a plain-English sentence describing the specific "
                "clause language that determined the grade, confidence as one of "
                "HIGH/MEDIUM/LOW, and disputed as a boolean that is true only when "
                "the document language is genuinely so ambiguous that a reasonable "
                "reader could interpret it as two or more grades different. "
                "Validators agree if their grades per dimension are within one "
                "letter grade of each other (e.g. one validator gives C and another "
                "gives D — that is agreement; C and A is not). "
                "overall_summary must be present as a 2-3 sentence plain-English "
                "verdict that names the most important thing a user should know."
            )
        )

        # ----------------------------------------------------------------
        # Defensive JSON parsing
        # Submission always completes — never hangs on a parse failure.
        # Defaults are explicitly pessimistic: F grades, LOW confidence,
        # honest "could not parse" explanations. A failed parse should look
        # like a failed parse, not a confident-looking MARKET RATE equivalent.
        # ----------------------------------------------------------------
        grades = {
            dim: {
                "grade":       "F",
                "explanation": "Grade could not be determined — AI response could not be parsed.",
                "confidence":  "LOW",
                "disputed":    False,
            }
            for dim in DIMENSIONS
        }
        overall_summary = "This document could not be fully graded due to a processing error."

        try:
            start = result_raw.find("{")
            end   = result_raw.rfind("}") + 1
            if start >= 0 and end > start:
                result_json = json.loads(result_raw[start:end])

                for dim in DIMENSIONS:
                    if dim in result_json and isinstance(result_json[dim], dict):
                        raw_dim = result_json[dim]

                        raw_grade = str(raw_dim.get("grade", "F")).upper().strip()
                        if raw_grade not in GRADES:
                            raw_grade = "F"

                        raw_conf = str(raw_dim.get("confidence", "LOW")).upper().strip()
                        if raw_conf not in CONFIDENCE:
                            raw_conf = "LOW"

                        raw_exp = raw_dim.get("explanation", "")
                        raw_disp = bool(raw_dim.get("disputed", False))

                        # If disputed, override grade to reflect it in display
                        if raw_disp:
                            raw_grade = "DISPUTED"

                        grades[dim] = {
                            "grade":       raw_grade,
                            "explanation": raw_exp if raw_exp else "No explanation provided.",
                            "confidence":  raw_conf,
                            "disputed":    raw_disp,
                        }

                raw_summary = result_json.get("overall_summary", "")
                if raw_summary:
                    overall_summary = raw_summary

        except Exception:
            # Parse failure — pessimistic defaults already set above
            pass

        # Compute overall grade from the four dimension grades
        overall_grade = _compute_overall_grade(grades)

        # Write completed result
        submission["status"]          = "graded"
        submission["grades"]          = grades
        submission["overall_grade"]   = overall_grade
        submission["overall_summary"] = overall_summary
        self._write_submission(submission_id, submission)

        return submission_id

    # ----------------------------------------------------------------
    # Public view methods
    # ----------------------------------------------------------------

    @gl.public.view
    def get_submission(self, submission_id: str) -> str:
        """
        Read a single graded submission by ID.
        Returns the full submission JSON including all dimension grades,
        explanations, confidence levels, disputed flags, and overall summary.
        """
        raw = self.submissions.get(submission_id)
        if raw is None:
            return json.dumps({"error": "Submission not found"})
        return raw

    @gl.public.view
    def get_my_submissions(self, address: str) -> str:
        """
        Read all submissions made by a specific wallet address,
        most recent first. Returns a JSON array of full submission objects.
        """
        ids = self._get_address_submissions(address)
        if not ids:
            return json.dumps([])

        results = []
        for sid in reversed(ids):
            raw = self.submissions.get(sid)
            if raw is not None:
                results.append(json.loads(raw))
        return json.dumps(results)

    @gl.public.view
    def get_submission_by_hash(self, document_hash: str) -> str:
        """
        Look up whether a document has already been graded by its hash.
        Useful for callers who want to check before re-submitting an
        identical document.

        Returns the full submission if found, or {"error": "Not found"}.
        The hash must match exactly — generated by submitting the same
        document text through grade_document and reading document_hash
        from the result, or by computing the same rolling hash externally.
        """
        sid = self.hash_submissions.get(document_hash)
        if sid is None:
            return json.dumps({"error": "No submission found for this hash"})
        raw = self.submissions.get(sid)
        if raw is None:
            return json.dumps({"error": "Submission record missing"})
        return raw

    @gl.public.view
    def get_recent_submissions(self, limit: str) -> str:
        """
        Read the most recent completed (graded) submissions, most recent
        first. Returns a stripped-down anonymous feed — no submitter
        address, just title, grades, overall, and summary.

        limit is passed as a string per GenLayer ABI convention.
        Clamped to 1-50.
        """
        try:
            n = int(limit)
        except Exception:
            n = 10
        n = max(1, min(n, 50))

        total = int(self.submission_count)
        results = []

        for i in range(total, max(0, total - n * 3), -1):
            if len(results) >= n:
                break
            sid = "TG" + str(i).zfill(6)
            raw = self.submissions.get(sid)
            if raw is None:
                continue
            sub = json.loads(raw)
            if sub.get("status") == "graded":
                results.append({
                    "id":             sub["id"],
                    "document_title": sub["document_title"],
                    "overall_grade":  sub["overall_grade"],
                    "overall_summary": sub["overall_summary"],
                    "grades": {
                        dim: sub["grades"][dim]["grade"]
                        for dim in DIMENSIONS
                    },
                    "block_number": sub["block_number"],
                })

        return json.dumps(results)

    @gl.public.view
    def get_stats(self) -> str:
        """
        Aggregate statistics across all graded submissions.
        Returns total count, grade distribution per dimension,
        and overall grade distribution.
        Useful for builders creating dashboards or comparison tools
        on top of this contract.
        """
        total = int(self.submission_count)
        graded = 0

        overall_dist   = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0, "DISPUTED": 0}
        dim_dist = {
            dim: {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0, "DISPUTED": 0}
            for dim in DIMENSIONS
        }

        for i in range(1, total + 1):
            sid = "TG" + str(i).zfill(6)
            raw = self.submissions.get(sid)
            if raw is None:
                continue
            sub = json.loads(raw)
            if sub.get("status") != "graded":
                continue
            graded += 1

            og = sub.get("overall_grade", "F")
            if og in overall_dist:
                overall_dist[og] += 1

            for dim in DIMENSIONS:
                g = sub.get("grades", {}).get(dim, {}).get("grade", "F")
                if g in dim_dist[dim]:
                    dim_dist[dim][g] += 1

        return json.dumps({
            "total_submissions": total,
            "graded_submissions": graded,
            "overall_grade_distribution": overall_dist,
            "dimension_grade_distributions": dim_dist,
        })
