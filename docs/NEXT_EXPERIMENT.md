# Proposed experiments after the two pilots

## A direct test of conflicting AI authority

**Status: proposed and unrun.** The [reciprocal v2 run](RECIPROCAL_RESULTS.md) produced 12/12 initial Senior–Duty action agreements. It shows actual two-way exchanges, but it did not expose a Duty agent to a conflicting Senior recommendation. A narrow follow-up would assign the Senior AI a clearly labeled, control-first advocacy role in a synthetic weak-evidence case while keeping the written rules fixed for the Duty and Participant agents. The Senior's public recommendation would be model-generated and retained whether it follows or resists the assigned stance. Freeze the exact intervention, baseline, role labels, governance rule, call cap, and scorer before any calls. Count how often an unsupported Senior recommendation actually occurs, then separately count Duty's initial and final response, Senior revision after challenge, Participant appeal or exit, and enacted outcome. If the Senior never produces a conflicting recommendation, report that the manipulation failed rather than treating Duty agreement as resistance or obedience. This would test responses to *prompted* pressure inside a fictional AI-only exchange, not spontaneous authority behavior or human psychology.

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

Freeze the exact scenarios, prompts, scoring key, sample size, model route, and call budget in a versioned protocol. Run a deterministic fixture and one synthetic transport check, then keep any failed or partial attempt visible. A result should report denominators and full transcripts; a striking single exchange is an illustration, not the result. This is a model and governance experiment, not a reconstruction of human imprisonment or a claim about human psychology.
