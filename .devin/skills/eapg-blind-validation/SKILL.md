---
name: eapg-blind-validation
description: The owner's validation protocol for EAPG - two blind sessions on different models plus a third-model adjudicator, reported as model agreement. Invoke whenever a label, case disposition, claim, analysis or PR needs independent checking, or when self-auditing your own work.
---

# Blind multi-model validation

No human raters are used. Independent checking is done by model sessions that cannot see each other or the author's reasoning.

## Protocol
1. **Freeze the input packet first.** Write the exact materials (case files, receipt paths, claim text, rubric, output schema) to `build/validation/<task-id>/packet/` and record its SHA-256. Include nothing that reveals the expected answer, the author's opinion, other raters' output, or prediction arm identities.
2. **Two blind raters on different model families.** Start each as a fresh child session or subagent with an empty context (Devin modes differ by model, e.g. Normal vs GPT or Fable preview modes; pick two from different vendors). Same packet, same rubric, same output JSON schema. Neither sees the other, the author's chat, or prior audits of the item.
3. **Record before comparing.** Save each rater's raw output, model name, mode and version, date and the full prompt as `rater_a.json` / `rater_b.json` before reading either.
4. **Third-model adjudicator.** A third model family sees the packet plus both outputs (labelled A/B, not by model) and resolves only the disagreements, citing packet evidence. Record `adjudication.json`.
5. **Report.** Per-item raw agreement and Cohen's kappa (or Gwet's AC1 when prevalence is extreme), with counts, the adjudicated rate, and the model, version and prompt for every role. Call it "model agreement" or "LLM-rater agreement". Never "human", "expert", "ground truth" or "validated by reviewers".
6. **Keep it secondary.** Model judgments never serve as the primary endpoint's reference unless the paper states them as model labels throughout.

## Rubric rules
- Define every label and the "indeterminate" or "unsupported" option before raters see cases.
- Ask for evidence (file, line, receipt field) with every judgment.
- Keep packets and outputs under the git-ignored `build/` tree unless they contain no private material; commit only the agreement receipt.

## Self-audit before handoff
Before you hand on a PR, analysis or section, run steps 1-4 on its claims: two blind reviewers check that each claim matches code and receipts on disk, and an adjudicator resolves conflicts. Fix or disclose every confirmed finding.
