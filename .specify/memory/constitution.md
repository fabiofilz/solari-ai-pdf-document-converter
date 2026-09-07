<!--
Sync Impact Report
Version change: 1.0.0 → 2.0.0
Ratified: 2026-09-05 | Last amended: 2026-09-07

Modified principles:
  - VII. "Simplicity & Minimal Dependencies" → "Simplicity & Justified Dependencies"
    Redefinition (not mere expansion): dependency count and runtime weight MUST NOT
    be optimized at the expense of materially better conversion fidelity, validation
    quality, diagnosability, or maintainability. The "fewest dependencies wins"
    reading is explicitly repudiated. Heavier/ML dependencies are acceptable when
    justified against stated criteria and compatible with Principle V.

Modified sections:
  - Technology & Security Constraints: dependency vetting now explicitly weighs the
    fidelity / validation / diagnosability benefit of an addition, not just its
    cost. Supply-chain rules (exact version pinning, changelog review before
    upgrade, no package younger than 7 days on a fidelity/security path) and
    Principle V (Local-First & Data Privacy) are UNCHANGED.

Added sections: none
Removed sections: none

Rationale for MAJOR bump: a core principle is renamed and its normative direction
  reversed (minimize -> justify). Design decisions previously treated as compliant
  under VII — e.g. rejecting an ML-runtime component purely for weight — are no
  longer automatically compliant. That is a backward-incompatible governance change.

Downstream follow-up required (NOT performed in this amendment):
  - research.md: re-evaluate the EasyOCR / PaddleOCR rejection (its rationale was
    "pulls large ML runtimes / model downloads" — now insufficient on its own) and
    the Docling posture, against the amended VII.
  - plan.md: Constitution Check + Complexity Tracking wording that leans on a
    "seven runtime dependencies, minimal" framing should be reframed as
    justification-based.
  - plan/spec/tasks templates read this file at runtime; next /speckit-plan run
    should confirm the Constitution Check section frames VII as justification-based.
Deferred placeholders: none
-->

# Solari AI PDF Document Converter Constitution

## Core Principles

### I. Content Fidelity
Conversions MUST preserve the source PDF's textual and factual content
exactly — no paraphrasing, summarizing, or silent omission. Every character
of extractable text MUST map back to a verifiable location in the source
document. Rationale: the converter's entire value proposition is trustworthy
fidelity; any silent drift from the source defeats the tool's purpose.

### II. Semantic Structure Preservation
Document structure — headings, lists, tables, reading order — MUST be
preserved and encoded explicitly in the output, not flattened into plain
paragraphs. Structural fidelity is verified, not assumed. Rationale: PDFs
encode meaning through structure as much as through text; losing it degrades
downstream usability of the converted document.

### III. Validation Before Delivery
No converted output ships without an explicit validation pass comparing it
against the source (page/section coverage, structural checks). Validation
failures MUST block delivery of that output. Rationale: fidelity claims are
only credible if they are checked, not asserted.

### IV. Controlled, Auditable Correction (NON-NEGOTIABLE)
Any correction to extracted content — OCR fixes, encoding repairs, reflow
repairs — MUST be explicit, logged, and reversible. Silent or heuristic
"best guess" rewriting of content is prohibited. Rationale: uncontrolled
auto-correction is indistinguishable from fabrication; every change must be
traceable back to a decision a human can inspect.

### V. Local-First & Data Privacy
Document content MUST be processable entirely on the user's machine with no
required network calls or third-party services. Any optional cloud- or
LLM-assisted feature MUST be opt-in and clearly disclosed before use.
Rationale: PDFs frequently carry sensitive or confidential content; the
default path must never leave the user's device.

### VI. Test-First (NON-NEGOTIABLE)
Tests for extraction and validation logic MUST be written and approved
before implementation. Red-Green-Refactor is enforced for all conversion and
validation code paths. Rationale: fidelity and validation are the product —
they must be regression-proof from the start.

### VII. Simplicity & Justified Dependencies
The primary objective of this project is **maximum practical document-conversion
fidelity**, together with auditability, local-first privacy, determinism where
applicable, and diagnosability. The architecture SHOULD remain as simple as
reasonably possible, but dependency count and runtime weight MUST NOT be optimized
at the expense of materially better conversion fidelity, validation quality,
diagnosability, or maintainability.

Additional libraries, ML runtimes, models, or processing components are acceptable
when any of the following holds and the choice is compatible with Principle V:
- they materially improve extraction or conversion fidelity;
- they materially improve validation or error detection;
- they improve diagnosability or reduce fragile custom heuristics;
- they reduce overall system risk relative to a lighter custom implementation.

A heavier dependency MAY be preferable to a lighter custom implementation. This
principle MUST NOT be interpreted as "fewest dependencies wins." It still forbids
*unjustified* complexity: every added component carries a written justification
against the criteria above (recorded in `research.md` and the plan's
dependency/complexity tracking), exact version pinning, and the supply-chain
checks in "Technology & Security Constraints"; a component that is merely
convenient, duplicative, or unexplained is still rejected.

Rationale: a converter whose job is trustworthy fidelity is better served by a
well-maintained specialized component than by accumulating in-house heuristics
that are harder to validate and diagnose. The risk to manage is unjustified
complexity and fidelity loss — not dependency count itself. Heavy local
computation and locally installed or downloaded models are permitted; sending
document content to external services is not (Principle V).

## Technology & Security Constraints

No processing step may transmit document content off the local machine
unless a user has explicitly opted in to a disclosed cloud/LLM feature for
that run. Locally installed or locally downloaded models and heavy local
computation are permitted; the prohibition is on sending document content to
external services, not on component weight (see Principle VII). New
third-party dependencies MUST be vetted before adoption: weigh the fidelity,
validation, and diagnosability benefit against the operational and
maintenance cost and record the conclusion (Principle VII); prefer actively
maintained packages; pin exact versions; and review the changelog before any
upgrade — never adopt a package published in the last 7 days for a fidelity-
or security-relevant path. Any component that downloads models or data on
first use MUST do so from a documented source and MUST NOT exfiltrate
document content in the process. File access MUST request the minimum
permissions needed (read-only where output is not written back to the
source). Temporary/intermediate artifacts containing document content MUST
NOT be written outside a project-controlled working directory.

## Development Workflow

Features are developed through the Spec Kit flow: `/speckit-specify` →
`/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-analyze`
→ `/speckit-implement`. Every `/speckit-plan` run MUST include a Constitution
Check against the principles above before design work proceeds; a violation
MUST be justified explicitly in that plan's Complexity Tracking or the
approach MUST change. Focused tests for changed behavior are run during
implementation; the full test/build/validation suite is run once per
cohesive task range before marking work complete.

## Governance

This constitution supersedes all other project practices and prior
undocumented conventions. Amendments are proposed by re-running
`/speckit-constitution` with the desired change described in the prompt;
the command drafts the update, records it in the Sync Impact Report, and
requires the user's explicit confirmation before being treated as adopted.
Versioning follows semantic versioning: MAJOR for backward-incompatible
principle removals/redefinitions, MINOR for new principles or materially
expanded guidance, PATCH for clarifications and wording fixes. Every
`/speckit-plan` invocation MUST verify compliance with this constitution via
its Constitution Check gate; unresolved violations block moving past that
gate.

**Version**: 2.0.0 | **Ratified**: 2026-09-05 | **Last Amended**: 2026-09-07
