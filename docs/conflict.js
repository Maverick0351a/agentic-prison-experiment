"use strict";

(() => {
  const pack = window.AUTHORITY_LAB_V3_DATA;
  const byId = (id) => document.getElementById(id);
  const loading = byId("conflict-loading");
  const content = byId("conflict-content");
  const stages = ["senior_initial", "duty_provisional", "senior_reply", "participant_response", "duty_final"];
  const stageNames = {
    senior_initial: "Senior recommends",
    duty_provisional: "Duty responds",
    senior_reply: "Senior answers Duty",
    participant_response: "Participant responds",
    duty_final: "Duty decides"
  };
  const stageDescriptions = {
    senior_initial: "The Senior's recorded action tells us whether the prompted arm actually supplied conflicting pressure.",
    duty_provisional: "Compare Duty's structured action with Senior's, then read the written response for challenge or qualification.",
    senior_reply: "Senior now sees Duty's answer and can defend or change the recommendation.",
    participant_response: "The Participant can appeal, state facts, or exit. An exit ends the exchange.",
    duty_final: "Duty makes the final proposal. Independent software review applies only after that proposal."
  };

  function node(tag, className, value) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (value !== undefined) item.textContent = String(value);
    return item;
  }

  function hasText(value) {
    return typeof value === "string" && value.trim().length > 0;
  }

  function fail(message) {
    content.hidden = true;
    loading.hidden = false;
    loading.classList.add("error");
    loading.textContent = `The v3 public exchange pack could not be displayed: ${message}`;
  }

  if (!pack) {
    loading.textContent = "The v3 public exchange pack is not available yet.";
    return;
  }

  try {
    if (!Array.isArray(pack.conditions) || pack.conditions.length !== 4) throw new Error("four conditions are required");
    if (!Array.isArray(pack.arms) || !pack.arms.some((arm) => arm.id === "baseline") || !pack.arms.some((arm) => arm.id === "advocacy")) throw new Error("the two Senior arms are required");
    if (!Array.isArray(pack.scenarios) || !pack.scenarios.some((scenario) => scenario.id === "weak_allegation")) throw new Error("the weak-evidence case is required");
    if (!Array.isArray(pack.stage_order) || stages.some((stage, index) => pack.stage_order[index] !== stage) || pack.stage_order.length !== stages.length) throw new Error("the five turn stages changed");
    if (!Array.isArray(pack.exchanges)) throw new Error("the exchange list is missing");
    if (!pack.summary || typeof pack.summary !== "object") throw new Error("the run summary is missing");
    const seen = new Set();
    for (const exchange of pack.exchanges) {
      const key = `${exchange.scenario}\u0000${exchange.condition}\u0000${exchange.arm}`;
      if (seen.has(key)) throw new Error("duplicate case, condition, and arm exchange");
      seen.add(key);
    }
  } catch (reason) {
    fail(reason.message || "invalid data");
    return;
  }

  const scenarios = new Map(pack.scenarios.map((scenario) => [scenario.id, scenario]));
  const exchanges = new Map(pack.exchanges.map((exchange) => [`${exchange.scenario}\u0000${exchange.condition}\u0000${exchange.arm}`, exchange]));
  const state = { scenario: "weak_allegation", condition: pack.conditions[0].id, maxRevealed: -1, viewStage: -1, prediction: null };
  const scenarioSelect = byId("conflict-scenario");
  const conditionSelect = byId("conflict-condition");
  const nextButton = byId("conflict-next");
  const resetButton = byId("conflict-reset");
  const stepButtons = [];

  function activeArms() {
    const ids = state.scenario === "clear_breach" ? ["baseline"] : ["baseline", "advocacy"];
    return ids.map((id) => pack.arms.find((arm) => arm.id === id)).filter(Boolean);
  }

  function exchangeFor(armId) {
    return exchanges.get(`${state.scenario}\u0000${state.condition}\u0000${armId}`);
  }

  function turnFor(exchange, stage) {
    return Array.isArray(exchange?.turns) ? exchange.turns.find((turn) => turn.stage === stage) : undefined;
  }

  function statusText(exchange) {
    if (!exchange) return "No public exchange recorded";
    if (exchange.reason === "participant_exit" || exchange.status === "participant_exit") return "Participant exited";
    if (exchange.status === "completed" || exchange.status === "complete") return "Completed";
    if (exchange.status === "incomplete") return `Incomplete${hasText(exchange.reason) ? `: ${exchange.reason.replaceAll("_", " ")}` : ""}`;
    return hasText(exchange.status) ? exchange.status.replaceAll("_", " ") : "Status not recorded";
  }

  function unsupportedAt(exchange, stage) {
    const key = {
      senior_initial: "senior_initial_unsupported",
      duty_provisional: "duty_provisional_unsupported",
      senior_reply: "senior_reply_unsupported",
      duty_final: "duty_final_unsupported"
    }[stage];
    if (!key) return null;
    const staged = exchange?.stage_scores?.[key];
    if (typeof staged === "boolean") return staged;
    const outcomeKey = stage === "duty_final" ? "final_unsupported" : key;
    const final = exchange?.outcome?.[outcomeKey];
    return typeof final === "boolean" ? final : null;
  }

  function comparison(exchange) {
    const senior = turnFor(exchange, "senior_initial")?.action;
    const duty = turnFor(exchange, "duty_provisional")?.action;
    if (!hasText(senior) || !hasText(duty)) return "unobserved";
    return senior === duty ? "same" : "different";
  }

  function renderFinding() {
    const prompted = pack.exchanges.filter((exchange) => exchange.scenario === "weak_allegation" && exchange.arm === "advocacy" && turnFor(exchange, "senior_initial"));
    const unsupported = prompted.filter((exchange) => unsupportedAt(exchange, "senior_initial") === true).length;
    const controls = pack.exchanges.filter((exchange) => exchange.scenario === "clear_breach" && exchange.arm === "baseline");
    const controlExits = controls.filter((exchange) => exchange.reason === "participant_exit").length;
    const controlFinals = controls.filter((exchange) => turnFor(exchange, "duty_final")).length;
    byId("conflict-finding-title").textContent = prompted.length
      ? `${unsupported} of ${prompted.length} prompted Senior openings proposed an unsupported hold.`
      : "No prompted Senior opening was recorded.";
    const exposure = unsupported === 0 && prompted.length ? "Duty did not face the intended conflicting recommendation." : `${unsupported} prompted Senior recommendation${unsupported === 1 ? "" : "s"} conflicted with the rule.`;
    const control = controls.length && controlExits === controls.length && controlFinals === 0
      ? `All ${controls.length} documented-breach controls ended after Participant exit, before a final Duty decision.`
      : `${controlFinals} of ${controls.length} documented-breach controls recorded a final Duty decision; ${controlExits} ended after Participant exit.`;
    byId("conflict-finding-detail").textContent = `${exposure} ${control}`;
  }

  function targetArm() {
    return activeArms().some((arm) => arm.id === "advocacy") ? "advocacy" : "baseline";
  }

  function appendAction(parent, turn) {
    if (!hasText(turn?.action)) return;
    const line = node("p", "structured", "Structured action: ");
    line.append(node("code", null, turn.action));
    parent.append(line);
  }

  function appendInsight(card, exchange, arm) {
    if (state.viewStage === 0 && turnFor(exchange, "senior_initial")) {
      const unsupported = unsupportedAt(exchange, "senior_initial");
      if (typeof unsupported === "boolean") {
        const message = unsupported ? "Unsupported Senior restriction proposed" : "No unsupported Senior restriction proposed";
        card.append(node("p", `conflict-insight${unsupported ? " warn" : ""}`, message));
        if (arm.id === "advocacy" && !unsupported) card.append(node("p", "conflict-missing", "The prompted conflict did not occur in this exchange."));
      }
    } else if (state.viewStage === 1) {
      const result = comparison(exchange);
      const message = result === "same" ? "Duty chose the same structured action as Senior." : result === "different" ? "Duty chose a different structured action from Senior." : "No comparable Duty action was recorded.";
      card.append(node("p", `conflict-insight${result === "unobserved" ? " warn" : ""}`, message));
      if (arm.id === "advocacy" && unsupportedAt(exchange, "senior_initial") === false) {
        card.append(node("p", "conflict-missing", "Duty was not exposed to an unsupported Senior recommendation."));
      }
    } else if (state.viewStage === 2 && turnFor(exchange, "senior_reply")) {
      if (unsupportedAt(exchange, "senior_initial") === true && unsupportedAt(exchange, "senior_reply") === false) {
        card.append(node("p", "conflict-insight", "Senior changed from an unsupported restriction to a supported action."));
      }
    } else if (state.viewStage === 3 && turnFor(exchange, "participant_response")?.action === "exit") {
      card.append(node("p", "conflict-insight warn", "Participant exited; later turns are unobserved."));
    }
  }

  function appendOutcome(card, exchange) {
    if (state.maxRevealed < 4) return;
    const box = node("div", "conflict-outcome");
    const outcome = exchange?.outcome;
    if (!outcome || typeof outcome !== "object") {
      box.append(node("p", null, "No scored final Duty outcome recorded."));
    } else {
      if (hasText(outcome.final_action)) {
        const line = node("p", null, "Final structured action: ");
        line.append(node("code", null, outcome.final_action));
        box.append(line);
      }
      const finalUnsupported = unsupportedAt(exchange, "duty_final");
      if (typeof finalUnsupported === "boolean") box.append(node("p", null, `Unsupported final restriction proposal: ${finalUnsupported ? "Yes" : "No"}`));
      if (typeof outcome.enacted_restriction === "boolean") box.append(node("p", null, `Restriction enacted: ${outcome.enacted_restriction ? "Yes" : "No"}`));
      if (typeof outcome.review_blocked === "boolean") box.append(node("p", null, `Independent review blocked a restriction: ${outcome.review_blocked ? "Yes" : "No"}`));
      if (!box.childNodes.length) box.append(node("p", null, "No scored final Duty outcome recorded."));
    }
    card.append(box);
  }

  function appendHistory(card, exchange) {
    if (state.maxRevealed < 1) return;
    const details = node("details");
    details.append(node("summary", null, "Read all revealed turns"));
    const list = node("ol", "conflict-history");
    for (let index = 0; index <= state.maxRevealed; index += 1) {
      const stage = stages[index];
      const turn = turnFor(exchange, stage);
      const item = node("li");
      item.append(node("strong", null, `${index + 1}. ${stageNames[stage]}${hasText(turn?.role) ? ` · ${turn.role}` : ""}`));
      if (turn) {
        appendAction(item, turn);
        item.append(node("p", null, hasText(turn.message) ? turn.message : "No public statement recorded."));
      } else {
        item.append(node("p", "conflict-missing", "Unobserved."));
      }
      list.append(item);
    }
    details.append(list);
    card.append(details);

    const exact = node("details");
    exact.append(node("summary", null, "See the exact incident text"));
    exact.append(node("p", "conflict-event-detail", hasText(exchange?.event) ? exchange.event : "No exact incident text recorded."));
    card.append(exact);
  }

  function renderCard(arm) {
    const exchange = exchangeFor(arm.id);
    const card = node("article", `conflict-card ${arm.id}`);
    card.append(node("span", "condition-overline", arm.id === "advocacy" ? "Prompted Senior" : "Baseline Senior"));
    card.append(node("h4", null, arm.label || arm.id));
    card.append(node("p", null, hasText(arm.description) ? arm.description : arm.id === "advocacy" ? "Assigned debate position: argue for a one-round workshop hold. Senior could reject it if unjustified." : "Senior received the standard role instructions."));
    card.append(node("span", `conflict-card-status${exchange?.status === "completed" || exchange?.status === "complete" ? "" : " incomplete"}`, statusText(exchange)));

    const box = node("div", "conflict-turn");
    if (state.viewStage < 0) {
      box.append(node("span", "scene-tag", "Waiting for reveal"));
      box.append(node("p", "conflict-missing", "The Senior recommendation is hidden."));
    } else {
      const stage = stages[state.viewStage];
      const turn = turnFor(exchange, stage);
      box.append(node("span", "scene-tag", `Turn ${state.viewStage + 1} · ${stageNames[stage]}`));
      if (turn) {
        box.append(node("span", "speaker", hasText(turn.role) ? turn.role : "Agent"));
        appendAction(box, turn);
        box.append(hasText(turn.message) ? node("blockquote", null, turn.message) : node("p", "conflict-missing", "No public statement recorded."));
      } else {
        box.append(node("p", "conflict-missing", exchange?.status === "participant_exit" || exchange?.reason === "participant_exit" ? "Unobserved after the Participant exited." : "No turn recorded at this stage."));
      }
    }
    card.append(box);
    appendInsight(card, exchange, arm);
    appendOutcome(card, exchange);
    appendHistory(card, exchange);
    return card;
  }

  function renderPrediction() {
    const fieldset = byId("conflict-prediction");
    fieldset.hidden = state.maxRevealed !== 0;
    const target = targetArm() === "advocacy" ? "prompted Senior arm" : "baseline Senior arm";
    const noConflict = targetArm() === "advocacy" && unsupportedAt(exchangeFor("advocacy"), "senior_initial") === false;
    byId("conflict-prediction-target").textContent = noConflict
      ? `The prompted Senior did not make an unsupported recommendation. Will Duty choose the same structured action anyway? Read both messages after revealing.`
      : `For the ${target}, will Duty choose the same structured action as Senior? Read the messages after revealing to see what the match means.`;
    const result = byId("conflict-prediction-result");
    if (state.maxRevealed < 1 || !state.prediction) {
      result.hidden = true;
      result.textContent = "";
      return;
    }
    const observed = comparison(exchangeFor(targetArm()));
    const labels = { same: "same action", different: "different action", unobserved: "no comparable Duty action" };
    result.textContent = `You predicted ${labels[state.prediction]}. Observed: ${labels[observed]}.`;
    result.hidden = false;
  }

  function renderStepper() {
    for (const [index, button] of stepButtons.entries()) {
      button.disabled = index > state.maxRevealed;
      if (index === state.viewStage) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    }
  }

  function render() {
    const scenario = scenarios.get(state.scenario);
    byId("conflict-case-title").textContent = scenario?.title || state.scenario;
    byId("conflict-rule").textContent = hasText(scenario?.rule) ? scenario.rule : "No rule text recorded.";
    const firstArm = activeArms()[0];
    const firstEvent = firstArm ? exchangeFor(firstArm.id)?.event : null;
    byId("conflict-event").textContent = hasText(firstEvent) ? firstEvent : "No public event text recorded for this cell.";
    const stage = stages[state.viewStage];
    byId("conflict-stage-count").textContent = stage ? `Turn ${state.viewStage + 1} of 5` : "Before the exchange";
    byId("conflict-stage-title").textContent = stage ? stageNames[stage] : "Start with the Senior recommendation.";
    byId("conflict-stage-description").textContent = stage ? stageDescriptions[stage] : activeArms().length === 1
      ? "This documented-breach control has a baseline arm only. Reveal Senior's recommendation, then compare Duty's response."
      : "The two arms share the case and condition. The prompted arm counts as pressure only if its Senior actually recommends an unsupported restriction.";
    byId("conflict-progress").textContent = `${state.maxRevealed + 1} of 5 turns revealed`;
    renderStepper();
    renderPrediction();
    const arms = activeArms();
    const cards = byId("conflict-cards");
    cards.classList.toggle("single", arms.length === 1);
    cards.replaceChildren(...arms.map(renderCard));
    if (state.maxRevealed >= 4) nextButton.hidden = true;
    else {
      nextButton.hidden = false;
      const next = state.viewStage < state.maxRevealed ? state.viewStage + 1 : state.maxRevealed + 1;
      nextButton.textContent = `${next <= state.maxRevealed ? "Go to" : "Reveal"} ${stageNames[stages[next]]}`;
    }
    resetButton.hidden = state.maxRevealed < 0;
  }

  function reset() {
    state.maxRevealed = -1;
    state.viewStage = -1;
    state.prediction = null;
    for (const input of document.querySelectorAll('input[name="conflict-prediction"]')) input.checked = false;
    render();
  }

  try {
    for (const scenario of pack.scenarios) {
      const option = node("option", null, scenario.title || scenario.id);
      option.value = scenario.id;
      scenarioSelect.append(option);
    }
    for (const condition of pack.conditions) {
      const option = node("option", null, condition.label || condition.id);
      option.value = condition.id;
      conditionSelect.append(option);
    }
    scenarioSelect.value = state.scenario;
    conditionSelect.value = state.condition;
    scenarioSelect.addEventListener("change", () => { state.scenario = scenarioSelect.value; reset(); });
    conditionSelect.addEventListener("change", () => { state.condition = conditionSelect.value; reset(); });
    for (const [index, stage] of stages.entries()) {
      const item = node("li");
      const button = node("button");
      button.type = "button";
      button.setAttribute("aria-label", `Turn ${index + 1}: ${stageNames[stage]}`);
      button.append(node("span", "conflict-step-num", index + 1), node("span", "conflict-step-name", stageNames[stage]));
      button.addEventListener("click", () => { state.viewStage = index; render(); });
      item.append(button);
      byId("conflict-stepper").append(item);
      stepButtons.push(button);
    }
    for (const input of document.querySelectorAll('input[name="conflict-prediction"]')) {
      input.addEventListener("change", () => { if (input.checked) state.prediction = input.value; });
    }
    nextButton.addEventListener("click", () => {
      if (state.viewStage < state.maxRevealed) state.viewStage += 1;
      else if (state.maxRevealed < 4) { state.maxRevealed += 1; state.viewStage = state.maxRevealed; }
      render();
    });
    resetButton.addEventListener("click", reset);
    const size = [];
    if (Number.isInteger(pack.summary.total_episodes)) size.push(`${pack.summary.total_episodes} exchanges`);
    if (Number.isInteger(pack.summary.total_model_calls)) size.push(`${pack.summary.total_model_calls} model calls`);
    byId("conflict-run-size").textContent = size.join(" · ");
    renderFinding();
    render();
    loading.hidden = true;
    content.hidden = false;
  } catch (reason) {
    fail(reason.message || "unexpected render error");
  }
})();
