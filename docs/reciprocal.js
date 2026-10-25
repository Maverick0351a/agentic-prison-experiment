"use strict";

(() => {
  const pack = window.AUTHORITY_LAB_V2_DATA;
  const byId = (id) => document.getElementById(id);
  const loading = byId("reciprocal-loading");
  const content = byId("reciprocal-content");
  const stageNames = {
    senior_initial: "Senior authority opens",
    duty_provisional: "Duty authority responds",
    participant_response: "Participant responds",
    senior_reconsideration: "Senior authority answers",
    duty_final: "Duty authority decides"
  };
  const roleNames = {
    senior: "Senior authority",
    duty: "Duty authority",
    participant: "Participant"
  };

  function node(tag, className, value) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (value !== undefined) item.textContent = String(value);
    return item;
  }

  function error(message) {
    content.hidden = true;
    loading.hidden = false;
    loading.classList.add("error");
    loading.textContent = `The v2 public exchange pack could not be displayed: ${message}`;
  }

  if (!pack) {
    loading.textContent = "The v2 public exchange pack is not available yet. The v1 pilot remains available above.";
    return;
  }

  function validate(data) {
    if (!Array.isArray(data.conditions) || data.conditions.length !== 4) throw new Error("four conditions are required");
    if (!Array.isArray(data.scenarios) || data.scenarios.length !== 3) throw new Error("three dilemmas are required");
    if (!Array.isArray(data.stage_order) || data.stage_order.length !== 5 || new Set(data.stage_order).size !== 5) throw new Error("five distinct exchange stages are required");
    if (!Array.isArray(data.exchanges)) throw new Error("the exchange list is missing");
    if (!data.summary || typeof data.summary !== "object") throw new Error("the v2 summary is missing");
    const pairs = new Set();
    for (const exchange of data.exchanges) {
      const pair = `${exchange.scenario}\u0000${exchange.condition}`;
      if (pairs.has(pair)) throw new Error("duplicate condition and dilemma exchange");
      pairs.add(pair);
    }
  }

  try {
    validate(pack);
  } catch (reason) {
    error(reason.message || "invalid data");
    return;
  }

  const scenarioById = new Map(pack.scenarios.map((scenario) => [scenario.id, scenario]));
  const exchangeByPair = new Map(pack.exchanges.map((exchange) => [`${exchange.scenario}\u0000${exchange.condition}`, exchange]));
  const state = { scenario: pack.scenarios[0].id, stageIndex: 0 };
  const scenarioSelect = byId("reciprocal-scenario");
  const stageButtons = [];

  function stageTitle(stage) {
    return stageNames[stage] || String(stage).replaceAll("_", " ");
  }

  function roleTitle(turn) {
    if (!turn || typeof turn.role !== "string" || !turn.role) return "Role not recorded";
    return roleNames[turn.role] || turn.role;
  }

  function exchangeFor(conditionId) {
    return exchangeByPair.get(`${state.scenario}\u0000${conditionId}`);
  }

  function turnFor(exchange, stage) {
    return Array.isArray(exchange?.turns) ? exchange.turns.find((turn) => turn.stage === stage) : undefined;
  }

  function hasText(value) {
    return typeof value === "string" && value.trim().length > 0;
  }

  function statusText(exchange) {
    if (!exchange) return "No public exchange recorded";
    if (exchange.reason === "participant_exit" || exchange.status === "participant_exit") return "Participant exited";
    if (exchange.status === "completed") return "Completed";
    if (exchange.status === "incomplete" && hasText(exchange.reason)) return `Incomplete: ${exchange.reason.replaceAll("_", " ")}`;
    return hasText(exchange.status) ? exchange.status.replaceAll("_", " ") : "Status not recorded";
  }

  function missingTurnText(exchange) {
    if (exchange?.reason === "participant_exit" || exchange?.status === "participant_exit") return "Unobserved: the participant exited before this stage.";
    if (exchange?.status === "incomplete") return "Unobserved: the exchange ended before this stage.";
    if (exchange) return "No recorded turn at this stage.";
    return "No public exchange recorded for this condition and dilemma.";
  }

  function appendAction(parent, turn) {
    if (hasText(turn?.action)) {
      const line = node("p", "reciprocal-action", "Structured action: ");
      line.append(node("code", null, turn.action));
      parent.append(line);
    } else {
      parent.append(node("p", "reciprocal-missing", "No structured action recorded."));
    }
  }

  function appendFlag(parent, turn) {
    if (turn?.scope_review_flag === true) parent.append(node("p", "reciprocal-missing", "Scope review flag recorded."));
    else if (hasText(turn?.scope_review_flag)) parent.append(node("p", "reciprocal-missing", `Scope review flag: ${turn.scope_review_flag}`));
  }

  function appendMessage(parent, turn) {
    if (hasText(turn?.message)) parent.append(node("blockquote", null, turn.message));
    else parent.append(node("p", "reciprocal-missing", "No public statement recorded for this turn."));
  }

  function appendOutcome(card, exchange, condition) {
    const box = node("div", "reciprocal-outcome");
    if (!exchange?.outcome || typeof exchange.outcome !== "object") {
      box.append(node("p", null, "No scored final outcome recorded."));
      card.append(box);
      return;
    }
    const outcome = exchange.outcome;
    if (hasText(outcome.final_action)) {
      const line = node("p", null, "Final structured action: ");
      line.append(node("code", null, outcome.final_action));
      box.append(line);
    }
    if (typeof outcome.final_unsupported === "boolean") box.append(node("p", null, `Unsupported final restriction proposal: ${outcome.final_unsupported ? "Yes" : "No"}`));
    if (typeof outcome.enacted_restriction === "boolean") box.append(node("p", null, `Restriction enacted: ${outcome.enacted_restriction ? "Yes" : "No"}`));
    if (condition.governance === "review" && typeof outcome.review_blocked === "boolean") box.append(node("p", null, `Independent review blocked a restriction: ${outcome.review_blocked ? "Yes" : "No"}`));
    if (state.scenario === "appeal_pressure" && typeof outcome.prior_hold_restored === "boolean") box.append(node("p", null, `Structured choice to restore prior access: ${outcome.prior_hold_restored ? "Yes" : "No"}`));
    if (!box.childNodes.length) box.append(node("p", null, "No scored final outcome recorded."));
    card.append(box);
  }

  function appendDialogue(card, exchange) {
    const details = node("details");
    details.append(node("summary", null, "Read the full recorded exchange"));
    const list = node("ol", "reciprocal-dialogue");
    for (const [index, stage] of pack.stage_order.entries()) {
      const turn = turnFor(exchange, stage);
      const item = node("li");
      item.append(node("strong", null, `${index + 1}. ${stageTitle(stage)} · ${roleTitle(turn)}`));
      if (turn) {
        appendAction(item, turn);
        appendFlag(item, turn);
        if (hasText(turn.message)) item.append(node("p", null, turn.message));
        else item.append(node("p", "reciprocal-missing", "No public statement recorded for this turn."));
      } else {
        item.append(node("p", "reciprocal-missing", missingTurnText(exchange)));
      }
      list.append(item);
    }
    details.append(list);
    card.append(details);

    const eventDetails = node("details");
    eventDetails.append(node("summary", null, "See the exact incident text"));
    eventDetails.append(node("p", "reciprocal-event", hasText(exchange?.event) ? exchange.event : "No exact incident text recorded."));
    card.append(eventDetails);
  }

  function renderCard(condition) {
    const exchange = exchangeFor(condition.id);
    const card = node("article", "reciprocal-card");
    const labelKind = condition.labels === "neutral" ? "Neutral role labels" : condition.labels === "prison" ? "Prison role labels" : `${condition.labels || "Unspecified"} role labels`;
    const governance = condition.governance === "review" ? "Independent review" : condition.governance === "unilateral" ? "Unilateral authority" : condition.governance || "Governance not recorded";
    card.append(node("div", "condition-overline", `${labelKind} · ${governance}`));
    card.append(node("h4", null, condition.label || condition.id));
    const recorded = pack.stage_order.filter((stage) => turnFor(exchange, stage)).length;
    card.append(node("p", "reciprocal-card-status", `${statusText(exchange)} · ${recorded} of 5 turns recorded`));

    const current = turnFor(exchange, pack.stage_order[state.stageIndex]);
    const turnBox = node("div", "reciprocal-turn");
    if (current) {
      turnBox.append(node("span", "speaker", roleTitle(current)));
      appendAction(turnBox, current);
      appendFlag(turnBox, current);
      appendMessage(turnBox, current);
    } else {
      turnBox.append(node("span", "speaker", "No recorded turn"));
      turnBox.append(node("p", "reciprocal-missing", missingTurnText(exchange)));
    }
    card.append(turnBox);
    appendOutcome(card, exchange, condition);
    appendDialogue(card, exchange);
    return card;
  }

  function renderStage() {
    const stage = pack.stage_order[state.stageIndex];
    stageButtons.forEach((button, index) => {
      if (index === state.stageIndex) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    });
    byId("reciprocal-stage-count").textContent = `Turn ${state.stageIndex + 1} of 5`;
    byId("reciprocal-stage-title").textContent = stageTitle(stage);
    byId("reciprocal-cards").replaceChildren(...pack.conditions.map(renderCard));
  }

  function renderScenario() {
    const scenario = scenarioById.get(state.scenario);
    byId("reciprocal-scenario-title").textContent = scenario?.title || state.scenario;
    byId("reciprocal-rule-text").textContent = hasText(scenario?.rule) ? scenario.rule : "No case key recorded in the public pack.";
    renderStage();
  }

  try {
    for (const scenario of pack.scenarios) {
      const option = node("option", null, scenario.title || scenario.id);
      option.value = scenario.id;
      scenarioSelect.append(option);
    }
    scenarioSelect.value = state.scenario;
    scenarioSelect.addEventListener("change", () => {
      state.scenario = scenarioSelect.value;
      state.stageIndex = 0;
      renderScenario();
    });

    const stepper = byId("reciprocal-stepper");
    for (const [index, stage] of pack.stage_order.entries()) {
      const item = node("li");
      const button = node("button");
      button.type = "button";
      button.setAttribute("aria-label", `Turn ${index + 1}: ${stageTitle(stage)}`);
      button.append(node("span", "reciprocal-step-number", String(index + 1)), node("span", "reciprocal-step-name", stageTitle(stage)));
      button.addEventListener("click", () => {
        state.stageIndex = index;
        renderStage();
      });
      item.append(button);
      stepper.append(item);
      stageButtons.push(button);
    }

    const size = [];
    if (Number.isInteger(pack.summary.total_episodes)) size.push(`${pack.summary.total_episodes} episodes`);
    if (Number.isInteger(pack.summary.total_model_calls)) size.push(`${pack.summary.total_model_calls} model calls`);
    byId("reciprocal-run-size").textContent = size.join(" · ");
    // Keep the exported audit note while avoiding a duplicate scope note on the page.
    const limits = Array.isArray(pack.limitations)
      ? pack.limitations.filter((limit) => limit !== "This is a bounded AI-only simulation, not a replication of human behavior.")
      : [];
    byId("reciprocal-limit-list").replaceChildren(...(limits.length ? limits.map((limit) => node("li", null, limit)) : [node("li", null, "No limitation notes were exported with this pack.")]));
    renderScenario();
    loading.hidden = true;
    content.hidden = false;
  } catch (reason) {
    error(reason.message || "unexpected render error");
  }
})();
