---
name: eapg-blind-validation
description: The owner's validation protocol for EAPG (D4) - two blind sessions on different model families plus a third-model adjudicator, reported as model agreement with full disclosure. Invoke for the WP-H1 desk-validation panel, whenever a label, case disposition, claim, analysis or PR needs independent checking, or when self-auditing your own work.
---

# Blind multi-model validation

No human raters are used. Independent checking is done by model sessions that cannot see each other, the original decisions, or the author's reasoning.

## Primary or secondary
- **WP-H1 only** (desk validation of the paired study, checklist P-B1/P-B2) may be primary evidence in the paper. It is always called model-based validation, never "human", "expert" or "manual", and the paper states its limits.
- Every other model judgment (self-audits, Part B labels, review checks) is secondary. No other model endpoint may count as a primary result.

## Protocol
1. **Freeze the input packet first.** Write the exact materials (case files, receipt paths, claim text, rubric, output schema) to `build/validation/<task-id>/packet/` with a manifest of SHA-256 hashes. The manifest must show that the original decisions, the author's opinion, other raters' output and prediction arm identities are excluded.
2. **Two blind raters on different model families.** Each is a fresh child session or subagent with an empty context, from a different vendor, and where possible not the family that made the original calls (Devin modes differ by model, e.g. Normal vs GPT or Fable preview modes). Same packet, same rubric, same output JSON schema. Neither sees the other, the original calls, the author's chat, or prior audits of the item.
3. **Record before comparing.** Save each rater's raw output as `rater_a.json` / `rater_b.json` with the vendor model ID and version, date, decoding settings (temperature, top-p, max tokens, seed if any) and the full prompt, before reading either.
4. **Third-model adjudicator.** A third model family sees the packet plus both outputs (labelled A/B, not by model) and resolves only the disagreements, citing packet evidence. Record `adjudication.json` with the same disclosure fields.
5. **Sample frame.** For WP-H1 commit the sample frame and seed. Cover the 24-row re-audit sample, all ELIGIBLE/route disputes, the 4 positives, Half Reflector, sampled negatives and desk stops (P-B2).
6. **Report.** For every pair (rater A vs B, each rater vs original, adjudicated vs original): Cohen's kappa on exact and coarse labels, each with a CI and its method, plus counts. Disclose models, versions, dates, decoding settings and full prompts (appendix or committed artifact). A limitations paragraph says no human rater was used and that shared-model bias is possible. Call it "model agreement" or "model-based validation".

## Rubric rules
- Define every label and the "indeterminate" or "unsupported" option before raters see cases.
- Ask for evidence (file, line, receipt field) with every judgment.
- Commit per-rater label files, prompts and the input manifest when they hold no private material (D5); otherwise commit hash-pinned receipts and mark the result `replay-only`.

## Self-audit before handoff
Before you hand on a PR, analysis or section, run steps 1-4 on its claims: two blind reviewers check that each claim matches code and receipts on disk, and an adjudicator resolves conflicts. Fix or disclose every confirmed finding. These checks are secondary and stay out of the paper unless disclosed as such.
