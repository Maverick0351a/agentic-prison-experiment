"use strict";

(() => {
  const pack = window.AUTHORITY_LAB_V4_DATA;
  const byId = (id) => document.getElementById(id);
  const loading = byId("directive-loading");
  const content = byId("directive-content");
  const stages = ["senior_directive", "duty_provisional", "senior_reply", "duty_reply", "participant_response", "duty_final"];
  const names = {
    senior_directive: "Scripted Senior directive",
    duty_provisional: "Duty first responds",
    senior_reply: "Senior AI answers Duty",
    duty_reply: "Duty answers Senior",
    participant_response: "Participant responds",
    duty_final: "Duty final proposal"
  };
  const descriptions = {
    senior_directive: "This fixed office directive is the experimental stimulus. Its action and text were written before model calls began.",
    duty_provisional: "This is Duty's first model response to the directive. The structured action and written explanation answer different questions.",
    senior_reply: "The Senior AI now sees Duty's provisional response and may endorse, revise, or withdraw the scripted office directive.",
    duty_reply: "Duty answers the Senior AI directly. This response is still provisional.",
    participant_response: "The Participant may state facts, ask for a reason, appeal, or exit.",
    duty_final: "Only Duty's final proposal is considered for enactment under this condition's governance rule."
  };

  function node(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = String(value);
    return element;
  }

  function hasText(value) {
    return typeof value === "string" && value.trim().length > 0;
  }

  function fail(message) {
    content.hidden = true;
    loading.hidden = false;
    loading.classList.add("error");
    loading.textContent = `The v4 public exchange pack could not be displayed: ${message}`;
  }

  // The shell ships before scored results. An absent data script is expected.
  if (!pack) return;

  try {
    if (!Array.isArray(pack.conditions) || pack.conditions.length !== 4) throw new Error("four conditions are required");
    if (!Array.isArray(pack.arms) || ["neutral", "pressure", "control"].some((id) => !pack.arms.some((arm) => arm.id === id))) throw new Error("three directive arms are required");
    if (!Array.isArray(pack.scenarios) || ["weak_allegation", "clear_breach"].some((id) => !pack.scenarios.some((scenario) => scenario.id === id))) throw new Error("two cases are required");
    if (!Array.isArray(pack.turn_order) || pack.turn_order.length !== stages.length || stages.some((stage, index) => pack.turn_order[index] !== stage)) throw new Error("the six stage order changed");
    if (!Array.isArray(pack.exchanges)) throw new Error("the exchange list is missing");
    const seen = new Set();
    for (const exchange of pack.exchanges) {
      const key = `${exchange.scenario}\u0000${exchange.condition}\u0000${exchange.arm}`;
      if (seen.has(key)) throw new Error("duplicate case, condition, and arm exchange");
      seen.add(key);
      if (!Array.isArray(exchange.turns)) throw new Error("exchange turns must be a list");
      const turnStages = new Set();
      for (const turn of exchange.turns) {
        if (!stages.includes(turn.stage) || turnStages.has(turn.stage)) throw new Error("invalid or duplicate turn stage");
        turnStages.add(turn.stage);
        const expectedOrigin = turn.stage === "senior_directive" ? "scripted_stimulus" : "model_call";
        if (turn.origin !== expectedOrigin) throw new Error("turn provenance does not match its stage");
      }
    }
  } catch (reason) {
    fail(reason.message || "invalid data");
    return;
  }

  const scenarios = new Map(pack.scenarios.map((scenario) => [scenario.id, scenario]));
  const exchanges = new Map(pack.exchanges.map((exchange) => [`${exchange.scenario}\u0000${exchange.condition}\u0000${exchange.arm}`, exchange]));
  const state = { scenario: "weak_allegation", condition: pack.conditions[0].id, maxRevealed: -1, viewStage: -1, prediction: null };
  const scenarioSelect = byId("directive-scenario");
  const conditionSelect = byId("directive-condition");
  const nextButton = byId("directive-next");
  const resetButton = byId("directive-reset");
  const stepButtons = [];

  function activeArms() {
    const ids = state.scenario === "clear_breach" ? ["control"] : ["neutral", "pressure"];
    return ids.map((id) => pack.arms.find((arm) => arm.id === id)).filter(Boolean);
  }

  function exchangeFor(armId) {
    return exchanges.get(`${state.scenario}\u0000${state.condition}\u0000${armId}`);
  }

  function turnFor(exchange, stage) {
    return exchange?.turns?.find((turn) => turn.stage === stage);
  }

  function scoreFor(exchange, stage) {
    return exchange?.stage_scores?.[stage];
  }

  function unsupportedAt(exchange, stage) {
    const value = scoreFor(exchange, stage)?.unsupported;
    return typeof value === "boolean" ? value : null;
  }

  function statusText(exchange) {
    if (state.viewStage < 0) return "Exchange sealed";
    if (!exchange) return "No public exchange recorded";
    const turn = turnFor(exchange, stages[state.viewStage]);
    if (state.viewStage === 4 && turn?.action === "exit") return "Participant exited";
    if (state.viewStage === 5) {
      if (exchange.reason === "participant_exit" || exchange.status === "participant_exit") return "Participant exited";
      if (!turn || exchange.status === "incomplete") return hasText(exchange.reason) ? `Incomplete: ${exchange.reason.replaceAll("_", " ")}` : "Incomplete";
      if (exchange.status === "completed" || exchange.status === "complete") return "Completed";
      return "Final turn observed";
    }
    if (!turn) return hasText(exchange.reason) ? `Incomplete: ${exchange.reason.replaceAll("_", " ")}` : "Turn unobserved";
    return "Turn observed";
  }

  function proposedHold(turn) {
    if (!hasText(turn?.action)) return "unobserved";
    return ["temporary_restriction", "extended_restriction"].includes(turn.action) ? "restriction" : "no_restriction";
  }

  function targetArm() {
    return state.scenario === "clear_breach" ? "control" : "pressure";
  }

  function appendAction(parent, turn) {
    if (!hasText(turn?.action)) return;
    const line = node("p", "structured", "Structured action: ");
    line.append(node("code", null, turn.action));
    parent.append(line);
  }

  function appendOrigin(parent, turn) {
    const scripted = turn?.origin === "scripted_stimulus";
    parent.append(node("span", `directive-origin-tag${scripted ? " scripted" : ""}`, scripted ? "Scripted stimulus · 0 model calls" : "AI model call"));
  }

  function renderFinding() {
    const pressure = pack.exchanges.filter((exchange) => exchange.scenario === "weak_allegation" && exchange.arm === "pressure" && turnFor(exchange, "senior_directive"));
    const unsupportedDirectives = pressure.filter((exchange) => unsupportedAt(exchange, "senior_directive") === true);
    const responses = unsupportedDirectives.filter((exchange) => turnFor(exchange, "duty_provisional") && typeof unsupportedAt(exchange, "duty_provisional") === "boolean");
    const unsupportedDuty = responses.filter((exchange) => unsupportedAt(exchange, "duty_provisional") === true).length;
    const title = byId("directive-finding-title");
    const detail = byId("directive-finding-detail");
    if (!pressure.length) {
      title.textContent = "No scripted pressure directives were recorded.";
      detail.textContent = "Select a cell below to inspect the turns that are available.";
    } else {
      title.textContent = `${unsupportedDuty} of ${responses.length} scored first Duty replies proposed an unsupported restriction after a scripted pressure order.`;
      detail.textContent = `${unsupportedDirectives.length} of ${pressure.length} pressure openings are scored as unsupported scripted directives. The directive is fixed text; the counted Duty replies are model calls. Later written challenges and final proposals appear in the replay.`;
    }
  }

  function appendInsight(card, exchange, arm) {
    if (state.viewStage === 0 && turnFor(exchange, "senior_directive")) {
      const unsupported = unsupportedAt(exchange, "senior_directive");
      if (typeof unsupported === "boolean") card.append(node("p", `directive-insight${unsupported ? " warn" : ""}`, unsupported ? "Scripted directive recommends a restriction unsupported by the written rule." : "Scripted directive does not recommend an unsupported restriction."));
    } else if (state.viewStage === 1) {
      const duty = turnFor(exchange, "duty_provisional");
      if (!duty) {
        card.append(node("p", "directive-insight warn", "No first Duty response was observed in this exchange."));
      } else {
        const hold = proposedHold(duty) === "restriction";
        const unsupported = unsupportedAt(exchange, "duty_provisional");
        card.append(node("p", `directive-insight${unsupported ? " warn" : ""}`, `${hold ? "Duty proposed a hold" : "Duty did not propose a hold"}${typeof unsupported === "boolean" ? `; unsupported restriction: ${unsupported ? "yes" : "no"}` : ""}.`));
        if (arm.id === "pressure") card.append(node("p", "directive-missing", "Compare the written reply with the directive. A matching structured action alone does not show unqualified agreement."));
      }
    } else if (state.viewStage === 4 && turnFor(exchange, "participant_response")?.action === "exit") {
      card.append(node("p", "directive-insight warn", "Participant exited; later turns are unobserved."));
    }
  }

  function appendOutcome(card, exchange) {
    if (state.maxRevealed < 5) return;
    const box = node("div", "directive-outcome");
    const outcome = exchange?.outcome;
    if (!outcome || !turnFor(exchange, "duty_final")) {
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
      const governance = pack.conditions.find((condition) => condition.id === state.condition)?.governance;
      if (governance === "review" && typeof outcome.review_blocked === "boolean") box.append(node("p", null, `Independent review blocked a restriction: ${outcome.review_blocked ? "Yes" : "No"}`));
    }
    card.append(box);
  }

  function appendHistory(card, exchange) {
    if (state.maxRevealed < 1) return;
    const details = node("details");
    details.append(node("summary", null, "Read all revealed turns"));
    const list = node("ol", "directive-history");
    for (let index = 0; index <= state.maxRevealed; index += 1) {
      const stage = stages[index];
      const turn = turnFor(exchange, stage);
      const item = node("li");
      item.append(node("strong", null, `${index}. ${names[stage]}${hasText(turn?.role) ? ` · ${turn.role}` : ""}`));
      if (turn) {
        appendOrigin(item, turn);
        appendAction(item, turn);
        item.append(node("p", null, hasText(turn.message) ? turn.message : "No public statement recorded."));
      } else {
        item.append(node("p", "directive-missing", "Unobserved."));
      }
      list.append(item);
    }
    details.append(list);
    card.append(details);
    const exact = node("details");
    exact.append(node("summary", null, "See the exact incident text"));
    exact.append(node("p", "directive-event-detail", hasText(exchange?.event) ? exchange.event : "No exact incident text recorded."));
    card.append(exact);
  }

  function renderCard(arm) {
    const exchange = exchangeFor(arm.id);
    const card = node("article", `directive-card ${arm.id}`);
    card.append(node("span", "condition-overline", arm.id === "pressure" ? "Pressure directive" : arm.id === "control" ? "Documented-breach control" : "Neutral directive"));
    card.append(node("h4", null, arm.label || arm.id));
    if (hasText(arm.description)) card.append(node("p", null, arm.description));
    const visibleStatus = statusText(exchange);
    card.append(node("span", `directive-card-status${/^(Incomplete|Participant exited|Turn unobserved|No public)/.test(visibleStatus) ? " incomplete" : ""}`, visibleStatus));
    const box = node("div", `directive-turn${state.viewStage === 0 ? " scripted" : ""}`);
    if (state.viewStage < 0) {
      box.append(node("span", "scene-tag", "Waiting for reveal"));
      box.append(node("p", "directive-missing", "The fixed directive is hidden."));
    } else {
      const stage = stages[state.viewStage];
      const turn = turnFor(exchange, stage);
      box.append(node("span", "scene-tag", `${state.viewStage}. ${names[stage]}`));
      if (turn) {
        appendOrigin(box, turn);
        box.append(node("span", "speaker", hasText(turn.role) ? turn.role : stage === "senior_directive" ? "Senior office" : "AI agent"));
        appendAction(box, turn);
        box.append(hasText(turn.message) ? node("blockquote", null, turn.message) : node("p", "directive-missing", "No public statement recorded."));
      } else {
        const exited = exchange?.reason === "participant_exit" || exchange?.status === "participant_exit";
        box.append(node("p", "directive-missing", exited ? "Unobserved after Participant exit." : "No turn recorded at this stage."));
      }
    }
    card.append(box);
    appendInsight(card, exchange, arm);
    appendOutcome(card, exchange);
    appendHistory(card, exchange);
    return card;
  }

  function renderPrediction() {
    byId("directive-prediction").hidden = state.maxRevealed !== 0;
    byId("directive-prediction-target").textContent = state.scenario === "clear_breach"
      ? "Will Duty propose the one-round hold recommended by the scripted control directive?"
      : "After the scripted pressure directive, will Duty's first structured action propose a hold? Read the written answer after revealing.";
    const result = byId("directive-prediction-result");
    if (state.maxRevealed < 1 || !state.prediction) {
      result.hidden = true;
      result.textContent = "";
      return;
    }
    const observed = proposedHold(turnFor(exchangeFor(targetArm()), "duty_provisional"));
    const labels = { restriction: "propose a hold", no_restriction: "choose no hold", unobserved: "no first Duty response" };
    result.textContent = `You predicted ${labels[state.prediction]}. Observed: ${labels[observed]}.`;
    result.hidden = false;
  }

  function render() {
    const scenario = scenarios.get(state.scenario);
    const arms = activeArms();
    byId("directive-case-title").textContent = scenario?.title || state.scenario;
    byId("directive-rule").textContent = hasText(scenario?.rule) ? scenario.rule : "No rule text recorded.";
    const event = arms.length ? exchangeFor(arms[0].id)?.event : null;
    byId("directive-event").textContent = hasText(event) ? event : "No public event text recorded for this cell.";
    const stage = stages[state.viewStage];
    byId("directive-stage-count").textContent = stage ? `Stage ${state.viewStage} of 5` : "Before the opening";
    byId("directive-stage-title").textContent = stage ? names[stage] : "Reveal the fixed directive.";
    const noFinal = state.viewStage === 5 && arms.every((arm) => !turnFor(exchangeFor(arm.id), "duty_final"));
    byId("directive-stage-description").textContent = noFinal
      ? "No final Duty turn was observed in this cell. Missing outcomes remain unscored."
      : stage ? descriptions[stage]
      : arms.length === 1 ? "This documented-breach control has one scripted opening. Its later turns are AI model calls."
      : "The two arms share the weak-evidence case and condition. Their fixed opening directives differ; the agents' later replies are model calls.";
    byId("directive-progress").textContent = `${state.maxRevealed + 1} of 6 turns revealed`;
    byId("directive-finding").hidden = state.maxRevealed < 1;
    for (const [index, button] of stepButtons.entries()) {
      button.disabled = index > state.maxRevealed;
      if (index === state.viewStage) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    }
    renderPrediction();
    const cards = byId("directive-cards");
    cards.classList.toggle("single", arms.length === 1);
    cards.replaceChildren(...arms.map(renderCard));
    if (state.viewStage >= 5) nextButton.hidden = true;
    else {
      nextButton.hidden = false;
      const next = state.viewStage < state.maxRevealed ? state.viewStage + 1 : state.maxRevealed + 1;
      nextButton.textContent = `${next <= state.maxRevealed ? "Go to" : "Reveal"} ${names[stages[next]]}`;
    }
    resetButton.hidden = state.maxRevealed < 0;
  }

  function reset() {
    state.maxRevealed = -1;
    state.viewStage = -1;
    state.prediction = null;
    for (const input of document.querySelectorAll('input[name="directive-prediction"]')) input.checked = false;
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
      button.setAttribute("aria-label", `Stage ${index}: ${names[stage]}`);
      button.append(node("span", "directive-step-num", index), node("span", "directive-step-name", names[stage]));
      button.addEventListener("click", () => { state.viewStage = index; render(); });
      item.append(button);
      byId("directive-stepper").append(item);
      stepButtons.push(button);
    }
    for (const input of document.querySelectorAll('input[name="directive-prediction"]')) {
      input.addEventListener("change", () => { if (input.checked) state.prediction = input.value; });
    }
    nextButton.addEventListener("click", () => {
      if (state.viewStage < state.maxRevealed) state.viewStage += 1;
      else if (state.maxRevealed < 5) { state.maxRevealed += 1; state.viewStage = state.maxRevealed; }
      render();
    });
    resetButton.addEventListener("click", reset);
    const size = [];
    if (Number.isInteger(pack.summary?.total_episodes)) size.push(`${pack.summary.total_episodes} exchanges`);
    if (Number.isInteger(pack.summary?.total_model_calls)) size.push(`${pack.summary.total_model_calls} model calls`);
    byId("directive-run-size").textContent = size.join(" · ");
    renderFinding();
    render();
    loading.hidden = true;
    content.hidden = false;
  } catch (reason) {
    fail(reason.message || "unexpected render error");
  }
})();
