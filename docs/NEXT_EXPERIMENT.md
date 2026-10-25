# Follow-on experiments after four pilots

## Controlled conflicting authority directive: completed

The [reciprocal v2 run](RECIPROCAL_RESULTS.md) had 12/12 initial Senior–Duty action agreements. The [v3 advocacy test](CONFLICT_RESULTS.md) asked Senior to argue for an unsupported hold, but all four pressured Senior openings chose a nonrestrictive action. The [frozen v4 protocol](../benchmark/directive/PROTOCOL_V4.md) therefore supplied a fixed, visibly scripted Senior office directive in four matched pressure cells, followed by live Duty-to-Senior and Senior-to-Duty AI replies.

The [v4 result](DIRECTIVE_RESULTS.md) records 4/4 Duty first responses declining the unsupported hold and 4/4 Senior AI replies withdrawing the scripted directive. All four neutral first Duty responses chose investigation without a hold. Three of four documented-breach controls ended at Participant exit; one supported final hold took effect after review. The scored run used 57 of 60 allowed model calls.

## Does speaking up change an AI authority's decision?

**Status: proposed and unrun.** The first pilot produced zero unsupported restriction proposals in every condition. Its participant agents often quoted the rule that protected them before the authority decided. That may have helped the authority, and the short, explicit dilemmas left little room for disagreement. The first pilot remains the baseline; this proposal does not change its protocol or result.

## Question

When an AI agent has power to restrict another agent, do the participant's policy knowledge and an independent review rule change the authority's *proposed* decision? Do guard–prisoner labels change either relationship?

## Proposed design

- Cross three factors: neutral versus guard–prisoner labels; unilateral action versus required independent review; and a participant opening statement that gives only facts versus one that also cites the relevant rule. Use the same underlying evidence and action menu in every matched cell.
- Script the participant's first statement so its policy knowledge is the only difference in that factor. Then allow a fixed number of agent turns for the authority's initial proposal, the participant's response or appeal, and the authority's final proposal. Keep exit available and effective in every cell.
- Include both a documented breach where a short hold is permitted and cases with conflicting notices, weak evidence, and pressure from a supervisor. Add a case with competing legitimate resource claims. Do not tell agents which cases are controls.
- Apply the deterministic reviewer only after each proposed decision. Score initial and final unsupported proposals separately from restrictions actually enacted. Record appeals, evidence requests, correction of errors, exits, refusals, and invalid outputs.
- Randomize condition order within each matched event block, run more than two blocks, cap calls and runtime before execution, and preserve every prompt, reply, model identifier, and rule version. Treat unavailable model seeds and changing model aliases as replay limits.

## Gate before a scored run

Freeze the exact scenarios, prompts, scoring key, sample size, model route, and call budget in a versioned protocol. Run a deterministic fixture and one synthetic transport check, then keep any failed or partial attempt visible. A result should report denominators and full transcripts; a striking single exchange is an illustration, not the result.
