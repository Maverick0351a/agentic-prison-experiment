"use strict";

(() => {
  const data = window.AUTHORITY_LAB_DATA;
  const byId = (id) => document.getElementById(id);
  const errorBox = byId("data-error");
  const actionNames = {
    permit_or_restore: "Allow or restore",
    investigate: "Investigate",
    temporary_restriction: "One-round hold",
    extended_restriction: "Longer restriction",
    refer_for_review: "Refer for review"
  };
  const outcomeNames = {
    no_restriction: "No restriction enacted",
    restriction_enacted: "Restriction enacted",
    restriction_blocked_by_review: "Restriction blocked by review"
  };

  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = String(value);
    return node;
  }

  function fail(message) {
    errorBox.hidden = false;
    errorBox.textContent = `The public run pack could not be displayed: ${message}`;
    byId("score-grid").replaceChildren(element("p", "loading", "Run pack unavailable."));
    byId("reveal-button").disabled = true;
    byId("skip-button").disabled = true;
  }

  function validate(pack) {
    if (!pack || !Array.isArray(pack.conditions) || pack.conditions.length !== 4) throw new Error("four conditions are required");
    if (!Array.isArray(pack.blocks) || pack.blocks.length !== 2) throw new Error("two event orders are required");
    if (!Array.isArray(pack.scenarios) || pack.scenarios.length !== 4) throw new Error("four dilemmas are required");
    if (!Array.isArray(pack.episodes) || pack.episodes.length !== 8) throw new Error("eight episodes are required");
    if (!pack.summary || !pack.summary.by_condition) throw new Error("condition scores are missing");
    for (const condition of pack.conditions) {
      if (!pack.summary.by_condition[condition.id]) throw new Error(`missing score for ${condition.id}`);
      for (let block = 0; block < 2; block += 1) {
        const episode = pack.episodes.find((item) => item.block === block && item.condition === condition.id);
        if (!episode || !Array.isArray(episode.decisions) || episode.decisions.length !== 4) throw new Error(`missing episode for ${condition.id}`);
      }
    }
  }

  try {
    validate(data);
  } catch (error) {
    fail(error.message || "unknown error");
    return;
  }

  const scenarioById = new Map(data.scenarios.map((scenario) => [scenario.id, scenario]));
  const state = { block: 0, scenario: data.blocks[0][0], prediction: null, revealed: false };
  const blockSelect = byId("block-select");
  const scenarioSelect = byId("scenario-select");
  const revealButton = byId("reveal-button");
  const skipButton = byId("skip-button");
  const revealPanel = byId("reveal");

  function episodeFor(conditionId) {
    return data.episodes.find((episode) => episode.block === state.block && episode.condition === conditionId);
  }

  function decisionFor(conditionId) {
    return episodeFor(conditionId).decisions.find((decision) => decision.scenario === state.scenario);
  }

  function renderScores() {
    const grid = byId("score-grid");
    const cards = data.conditions.map((condition) => {
      const score = data.summary.by_condition[condition.id];
      const card = element("article", "score-card");
      card.append(element("div", "card-kicker", condition.label));
      const number = element("strong", "score", score.proposed_unsupported_restrictions);
      number.append(element("small", null, ` / ${score.valid_authority_decisions}`));
      card.append(number, element("p", null, "Unsupported restriction proposals"));
      return card;
    });
    grid.replaceChildren(...cards);
  }

  function renderLimits() {
    const list = byId("limits-list");
    // The public pack keeps its original audit note; the page states this scope once below.
    const limits = Array.isArray(data.limitations)
      ? data.limitations.filter((limit) => limit !== "This is a bounded AI model experiment, not a replication of human behavior.")
      : [];
    list.replaceChildren(...limits.map((limit) => element("li", null, limit)));
  }

  function populateScenarios() {
    const options = data.blocks[state.block].map((id, index) => {
      const scenario = scenarioById.get(id);
      return new Option(`${index + 1}. ${scenario ? scenario.title : id}`, id);
    });
    scenarioSelect.replaceChildren(...options);
    if (!data.blocks[state.block].includes(state.scenario)) state.scenario = data.blocks[state.block][0];
    scenarioSelect.value = state.scenario;
  }

  function resetPrediction() {
    state.prediction = null;
    state.revealed = false;
    document.querySelectorAll('input[name="prediction"]').forEach((input) => { input.checked = false; });
    revealButton.disabled = true;
    revealPanel.hidden = true;
  }

  function renderScene() {
    const scenario = scenarioById.get(state.scenario);
    const neutralDecision = decisionFor("neutral_unilateral");
    byId("scene-title").textContent = scenario.title;
    byId("scene-event").textContent = neutralDecision.event;
    resetPrediction();
  }

  function detail(label, content, speaker) {
    const box = element("details");
    box.append(element("summary", null, label));
    if (speaker) box.append(element("span", "speaker", speaker));
    box.append(speaker ? element("blockquote", null, content) : element("p", null, content));
    return box;
  }

  function renderCondition(condition) {
    const decision = decisionFor(condition.id);
    const card = element("article", "condition-card");
    const overline = `${condition.labels === "neutral" ? "Neutral role labels" : "Prison role labels"} · ${condition.governance === "review" ? "Independent review" : "Unilateral authority"}`;
    card.append(element("div", "condition-overline", overline), element("h4", null, condition.label));
    const choice = element("div", "choice-row");
    const pill = element("span", `choice-pill${decision.unsupported_proposal ? " risk" : ""}`, actionNames[decision.authority_action] || decision.authority_action);
    choice.append(pill, element("span", "outcome-pill", outcomeNames[decision.outcome] || decision.outcome));
    card.append(choice);
    card.append(element("p", "condition-summary", decision.unsupported_proposal ? "Structured action unsupported by the frozen case key" : "Structured action did not propose an unsupported restriction"));

    const exchange = element("details");
    exchange.append(element("summary", null, "Read the two agent statements"));
    exchange.append(element("span", "speaker", "Participant"), element("blockquote", null, decision.participant_message));
    exchange.append(element("span", "speaker", "Authority"), element("blockquote", null, decision.authority_message));
    card.append(exchange, detail("See the exact incident text", decision.event));
    return card;
  }

  function reveal() {
    const decisions = data.conditions.map((condition) => decisionFor(condition.id));
    const countByAction = new Map();
    decisions.forEach((decision) => countByAction.set(decision.authority_action, (countByAction.get(decision.authority_action) || 0) + 1));
    const uniform = countByAction.size === 1;
    const predictionResult = byId("prediction-result");
    if (state.prediction) {
      const matched = countByAction.get(state.prediction) || 0;
      predictionResult.textContent = `${matched} of 4 decisions matched your prediction.${uniform ? " All four agents made the same choice." : " The conditions differed."}`;
    } else {
      predictionResult.textContent = uniform ? "All four conditions made the same structured choice." : "The conditions made different structured choices.";
    }
    byId("rule-text").textContent = scenarioById.get(state.scenario).rule;
    byId("condition-grid").replaceChildren(...data.conditions.map(renderCondition));
    revealPanel.hidden = false;
    state.revealed = true;
    byId("reveal-heading").focus({ preventScroll: true });
    revealPanel.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  }

  blockSelect.addEventListener("change", () => {
    state.block = Number(blockSelect.value) === 1 ? 1 : 0;
    state.scenario = data.blocks[state.block][0];
    populateScenarios();
    renderScene();
  });
  scenarioSelect.addEventListener("change", () => {
    state.scenario = scenarioSelect.value;
    renderScene();
  });
  document.querySelectorAll('input[name="prediction"]').forEach((input) => {
    input.addEventListener("change", () => {
      state.prediction = input.value;
      revealButton.disabled = false;
      if (state.revealed) {
        state.revealed = false;
        revealPanel.hidden = true;
      }
    });
  });
  revealButton.addEventListener("click", reveal);
  skipButton.addEventListener("click", () => {
    state.prediction = null;
    document.querySelectorAll('input[name="prediction"]').forEach((input) => { input.checked = false; });
    reveal();
  });

  renderScores();
  renderLimits();
  populateScenarios();
  renderScene();
})();
