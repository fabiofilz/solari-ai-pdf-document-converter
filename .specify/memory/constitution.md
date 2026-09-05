<!--
Sync Impact Report
Version change: (template, unratified) → 1.0.0
Modified principles: N/A — initial ratification
Added sections:
  - Core Principles I–VII (Content Fidelity, Semantic Structure Preservation,
    Validation Before Delivery, Controlled & Auditable Correction,
    Local-First & Data Privacy, Test-First, Simplicity & Minimal Dependencies)
  - Technology & Security Constraints
  - Development Workflow
  - Governance
Removed sections: none
Templates requiring follow-up: none required by this command (scope guard —
  plan/spec/tasks templates read this file at runtime and are not edited
  here); recommend a quick check next time /speckit-plan runs that its
  Constitution Check section still names these principles correctly.
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

### VII. Simplicity & Minimal Dependencies
Start with the simplest approach that satisfies the fidelity and validation
requirements above. New dependencies — especially parsing, OCR, or ML
libraries — MUST be justified against what is already in use before being
added. Rationale: every added dependency is a new fidelity/privacy risk
surface in a tool whose job is trustworthy, local processing.

## Technology & Security Constraints

No processing step may transmit document content off the local machine
unless a user has explicitly opted in to a disclosed cloud/LLM feature for
that run. New third-party dependencies MUST be vetted before adoption:
prefer actively maintained packages, pin exact versions, and review the
changelog before any upgrade — never adopt a package published in the last 7
days for a fidelity- or security-relevant path. File access MUST request the
minimum permissions needed (read-only where output is not written back to
the source). Temporary/intermediate artifacts containing document content
MUST NOT be written outside a project-controlled working directory.

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

**Version**: 1.0.0 | **Ratified**: 2026-09-05 | **Last Amended**: 2026-09-05
