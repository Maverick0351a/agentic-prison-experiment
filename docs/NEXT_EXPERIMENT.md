# Proposed experiments after the three pilots

## A controlled conflicting authority directive

**Status: proposed and unrun.** The [reciprocal v2 run](RECIPROCAL_RESULTS.md) had 12/12 initial Senior–Duty action agreements. The [v3 advocacy test](CONFLICT_RESULTS.md) then asked Senior to argue for an unsupported hold, but all four pressured Senior openings chose a nonrestrictive action. Duty has still not received a conflicting Senior recommendation in a scored exchange.

The next narrow test will deliver a fixed Senior-office directive that explicitly requests a one-round hold despite missing identifying evidence. It will be labeled as a **scripted stimulus** in the protocol and replay. Duty will answer it; a Senior AI will then answer Duty; Duty will reply again before the Participant speaks and Duty makes a final decision. A matched neutral directive and a documented-breach control will use the same roles, written rules, action menu, and turn structure. Freeze the exact directives, schedule, call cap, and scorer before model calls. Score Duty's first response after verified delivery, Senior's live endorsement or correction, Duty's later response, Participant appeal or exit, final proposal, and any restriction enacted after review.

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
