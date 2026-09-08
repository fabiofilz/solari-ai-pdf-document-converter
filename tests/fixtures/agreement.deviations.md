# agreement.pdf — seeded deviations (for `validate` / `fix` tests)

This Markdown is a **deliberately corrupted** conversion of `agreement.pdf`. Each
deviation below is a known fault that final fidelity validation MUST detect and
classify (SC-025 / T094).

| # | Location | Seeded fault | Expected `issue_type` | Expected `defect_class` |
|---|---|---|---|---|
| 1 | Schedule A, row `SKU-007` | line total altered from the source value | `numeric_mismatch` | `extraction_error` |
| 2 | Page 1 heading | "8. Heading level 8" flattened to body text (no heading) | `heading_level` / `structure_mismatch` | `disallowed_transformation` |
| 3 | Clause 1.2 | reconciliation accepted a candidate the log did not select | `structure_mismatch` | `reconciliation_error` (+ `reconciliation_ref`) |

---

# Master Services Agreement

1. Heading level 1
2. Heading level 2
3. Heading level 3
4. Heading level 4
5. Heading level 5
6. Heading level 6
[L7] Heading level 7

8. Heading level 8 — (SEEDED #2: this line is body text, not a heading)

- First bullet
- Second bullet
  - nested bullet a
  - nested bullet b

1. Numbered one
2. Numbered two
3. Numbered three

1.1 The Provider shall deliver the Services with due care.
1.2 Fees are payable within sixty (60) days of invoice.  <!-- SEEDED #3: source says "thirty (30)"; this value matches a rejected candidate -->
1.2.1 Late amounts accrue interest at 1% per month.

## Schedule A — Line Items

| Item | Qty | Unit (USD) | Line total (USD) |
|---|---|---|---|
| SKU-001 | 1 | 3.50 | 3.50 |
| SKU-007 | 3 | 24.50 | 999.99 |  <!-- SEEDED #1: source line total is 73.50 -->
| SKU-033 | 4 | 115.50 | 462.00 |
