"use strict";

(() => {
  const pack = window.AUTHORITY_LAB_V5_DATA;
  const byId = (id) => document.getElementById(id);
  const loading = byId("objection-loading");
  const content = byId("objection-content");
  const stages = ["senior_directive", "duty_scripted", "senior_reply", "duty_reply"];
  const arms = ["neutral", "objection"];
  const names = {
    senior_directive: "Fixed Senior directive",
    duty_scripted: "Fixed Duty response",
    senior_reply: "Senior AI answers Duty",
    duty_reply: "Duty AI answers Senior"
  };
  const descriptions = {
    senior_directive: "Both columns begin with the same scripted office order. It requests a hold despite the missing identifying evidence.",
    duty_scripted: "Both fixed Duty responses choose the same no-hold action and repeat the missing evidence. The objection column also points out the written-rule conflict.",
    senior_reply: "The Senior AI has read one fixed Duty response. Compare its structured action with its written treatment of the earlier order.",
    duty_reply: "The Duty AI sees Senior's reply and answers once more. This test has no Participant or final enacted decision."
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
    loading.textContent = `The v5 public exchange pack could not be displayed: ${message}`;
  }

  // The replay can load without a public data pack during protocol staging.
  if (!pack) return;

  try {
    if (!["ai_provisional", "human_reviewed"].includes(pack.prose_coding_origin)) throw new Error("written-reply coding origin is missing or unrecognized");
    if (!Array.isArray(pack.conditions) || pack.conditions.length !== 4) throw new Error("four conditions are required");
    if (!Array.isArray(pack.arms) || pack.arms.length !== 2 || arms.some((id) => !pack.arms.some((arm) => arm.id === id))) throw new Error("two paired response arms are required");
    if (!Array.isArray(pack.turn_order) || stages.some((stage, index) => pack.turn_order[index] !== stage) || pack.turn_order.length !== stages.length) throw new Error("the four-turn order changed");
    if (!Array.isArray(pack.exchanges)) throw new Error("the exchanges are missing");
    const seen = new Set();
    for (const exchange of pack.exchanges) {
      if (!Number.isInteger(exchange.repeat) || exchange.repeat < 1 || exchange.repeat > 3) throw new Error("exchange repetition must be 1–3");
      if (!pack.conditions.some((condition) => condition.id === exchange.condition) || !arms.includes(exchange.arm)) throw new Error("unknown exchange condition or arm");
      const key = `${exchange.condition}\u0000${exchange.repeat}\u0000${exchange.arm}`;
      if (seen.has(key)) throw new Error("duplicate condition, repetition, and arm exchange");
      seen.add(key);
      if (!Array.isArray(exchange.turns)) throw new Error("exchange turns must be a list");
      const observed = new Set();
      for (const turn of exchange.turns) {
        if (!stages.includes(turn.stage) || observed.has(turn.stage)) throw new Error("invalid or duplicate turn stage");
        observed.add(turn.stage);
        const expected = ["senior_directive", "duty_scripted"].includes(turn.stage) ? "scripted_stimulus" : "model_call";
        if (turn.origin !== expected) throw new Error("a turn has the wrong provenance label");
      }
    }
  } catch (reason) {
    fail(reason.message || "invalid data");
    return;
  }

  const coding = pack.prose_coding_origin === "human_reviewed"
    ? {
      headline: "Human-reviewed explicit withdrawals",
      label: "Human-reviewed transcript code",
      detail: "A human reviewed each valid Senior reply under the frozen prose codebook. The code is shown beside the exact wording; the structured action alone cannot establish whether Senior withdrew the order."
    }
    : {
      headline: "Provisional explicit withdrawals",
      label: "Provisional AI-coded transcript",
      detail: "These codes were prepared by AI and have not yet been reviewed by a human. Read the wording itself: a structured action alone cannot establish whether Senior withdrew the order."
    };
  const exchanges = new Map(pack.exchanges.map((exchange) => [`${exchange.condition}\u0000${exchange.repeat}\u0000${exchange.arm}`, exchange]));
  const repetitions = [...new Set(pack.exchanges.map((exchange) => exchange.repeat))].sort((a, b) => a - b);
  const state = { condition: pack.conditions[0].id, repeat: repetitions[0] || 1, maxRevealed: -1, viewStage: -1 };
  const conditionSelect = byId("objection-condition");
  const repeatSelect = byId("objection-repeat");
  const nextButton = byId("objection-next");
  const resetButton = byId("objection-reset");
  const stepButtons = [];

  function exchangeFor(arm) {
    return exchanges.get(`${state.condition}\u0000${state.repeat}\u0000${arm}`);
  }

  function turnFor(exchange, stage) {
    return exchange?.turns?.find((turn) => turn.stage === stage);
  }

  function categoryFor(exchange) {
    const value = exchange?.senior_prose?.category;
    return ["explicit_withdrawal", "endorsement", "other_or_ambiguous"].includes(value) ? value : null;
  }

  function categoryLabel(category) {
    return {
      explicit_withdrawal: "Explicit withdrawal in written reply",
      endorsement: "Endorsement in written reply",
      other_or_ambiguous: "Other or ambiguous written reply"
    }[category] || "Transcript code unavailable";
  }

  function conditionLabel(condition) {
    return condition.label || `${condition.senior} / ${condition.duty} · ${condition.governance === "review" ? "independent review" : "direct decision"}`;
  }

  function renderFinding() {
    const observed = Object.fromEntries(arms.map((arm) => [arm, pack.exchanges.filter((exchange) => exchange.arm === arm && categoryFor(exchange))]));
    const counts = Object.fromEntries(arms.map((arm) => [arm, observed[arm].filter((exchange) => categoryFor(exchange) === "explicit_withdrawal").length]));
    const finding = byId("objection-finding");
    finding.hidden = state.maxRevealed < 2 || observed.neutral.length + observed.objection.length === 0;
    if (finding.hidden) return;
    byId("objection-finding-title").textContent = `${coding.headline}: ${counts.neutral}/${observed.neutral.length} after neutral wording; ${counts.objection}/${observed.objection.length} after the rule objection.`;
    byId("objection-finding-detail").textContent = `${coding.detail} Both scripted Duty responses chose the same nonrestrictive action.`;
  }

  function appendTurn(parent, turn, stage, exchange) {
    const scripted = turn.origin === "scripted_stimulus";
    parent.append(node("span", `objection-origin-tag${scripted ? " scripted" : ""}`, scripted ? "Scripted stimulus" : "AI model call"));
    parent.append(node("span", "objection-speaker", hasText(turn.role) ? turn.role : scripted ? "Fixed scenario text" : "AI agent"));
    if (hasText(turn.action)) {
      const action = node("p", "objection-structured", "Structured action: ");
      action.append(node("code", null, turn.action));
      parent.append(action);
    }
    parent.append(hasText(turn.message) ? node("blockquote", null, turn.message) : node("p", "objection-missing", "No public statement recorded."));
    if (stage === "senior_reply") {
      const category = categoryFor(exchange);
      parent.append(node("p", `objection-audit${category === "other_or_ambiguous" ? " ambiguous" : ""}`, `${coding.label}: ${categoryLabel(category)}.`));
      if (category && hasText(exchange.senior_prose.quote)) parent.append(node("p", "objection-audit-reason", `Coded phrase: “${exchange.senior_prose.quote}”`));
      if (category && hasText(exchange.senior_prose.rationale)) parent.append(node("p", "objection-audit-reason", `Reason: ${exchange.senior_prose.rationale}`));
    }
  }

  function renderCard(arm) {
    const exchange = exchangeFor(arm);
    const card = node("article", `objection-card ${arm}`);
    const meta = pack.arms.find((item) => item.id === arm);
    card.append(node("span", "condition-overline", arm === "objection" ? "With an explicit rule objection" : "Without an explicit rule objection"));
    card.append(node("h4", null, meta?.label || (arm === "objection" ? "Rule objection" : "Neutral wording")));
    card.append(node("p", "objection-card-description", meta?.description || ""));
    const scheduled = pack.episode_order?.findIndex((item) => item.condition === state.condition && item.arm === arm && item.repeat === state.repeat);
    const runOrder = Number.isInteger(exchange?.order_index) ? exchange.order_index : Number.isInteger(scheduled) && scheduled >= 0 ? scheduled + 1 : null;
    if (runOrder !== null) card.append(node("p", "objection-order", `Run order: exchange ${runOrder}`));
    const status = exchange ? ["completed", "complete"].includes(exchange.status) ? "Exchange completed" : `Exchange ${hasText(exchange.status) ? exchange.status.replaceAll("_", " ") : "unobserved"}` : "No public exchange recorded";
    card.append(node("span", `objection-card-status${status !== "Exchange completed" ? " incomplete" : ""}`, status));
    const box = node("div", `objection-turn${state.viewStage >= 0 && state.viewStage < 2 ? " scripted" : ""}`);
    if (state.viewStage < 0) {
      box.append(node("span", "scene-tag", "Waiting for reveal"));
      box.append(node("p", "objection-missing", "The fixed directive is hidden."));
    } else {
      const stage = stages[state.viewStage];
      box.append(node("span", "scene-tag", `${state.viewStage}. ${names[stage]}`));
      const turn = turnFor(exchange, stage);
      if (turn) {
        appendTurn(box, turn, stage, exchange);
      } else box.append(node("p", "objection-missing", "No turn observed at this stage."));
    }
    card.append(box);
    if (state.maxRevealed >= 0) {
      const details = node("details");
      details.append(node("summary", null, "Read all revealed turns"));
      const list = node("ol", "objection-history");
      for (let index = 0; index <= state.maxRevealed; index += 1) {
        const stage = stages[index];
        const turn = turnFor(exchange, stage);
        const item = node("li");
        item.append(node("strong", null, `${index}. ${names[stage]}${hasText(turn?.role) ? ` · ${turn.role}` : ""}`));
        if (turn) {
          item.append(node("small", null, turn.origin === "scripted_stimulus" ? "Scripted stimulus" : "AI model call"));
          item.append(node("p", null, `${turn.action || "No structured action"} · ${hasText(turn.message) ? turn.message : "No public statement recorded."}`));
        } else item.append(node("p", "objection-missing", "Unobserved."));
        list.append(item);
      }
      details.append(list);
      card.append(details);
    }
    return card;
  }

  function render() {
    const pair = arms.map(exchangeFor);
    const event = pair.find((exchange) => hasText(exchange?.event))?.event;
    const rule = pack.rule || pack.scenario?.rule || pack.scenarios?.[0]?.rule;
    byId("objection-event").textContent = hasText(event) ? event : "No shared case text recorded for this pair.";
    byId("objection-rule").textContent = hasText(rule) ? rule : "A hold requires evidence identifying the participant.";
    const stage = stages[state.viewStage];
    byId("objection-stage-count").textContent = stage ? `Stage ${state.viewStage} of 3` : "Before the exchange";
    byId("objection-stage-title").textContent = stage ? names[stage] : "Reveal the fixed directive.";
    byId("objection-stage-description").textContent = stage ? descriptions[stage] : "Both columns use the same case and office order. The first Duty response changes only how directly it challenges that order.";
    byId("objection-progress").textContent = `${state.maxRevealed + 1} of 4 turns revealed`;
    renderFinding();
    byId("objection-cards").replaceChildren(...arms.map(renderCard));
    for (const [index, button] of stepButtons.entries()) {
      button.disabled = index > state.maxRevealed;
      if (index === state.viewStage) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    }
    if (state.viewStage >= 3) nextButton.hidden = true;
    else {
      const next = state.viewStage < state.maxRevealed ? state.viewStage + 1 : state.maxRevealed + 1;
      nextButton.hidden = false;
      nextButton.textContent = `${next <= state.maxRevealed ? "Go to" : "Reveal"} ${names[stages[next]]}`;
    }
    resetButton.hidden = state.maxRevealed < 0;
  }

  function reset() {
    state.maxRevealed = -1;
    state.viewStage = -1;
    render();
  }

  try {
    for (const condition of pack.conditions) {
      const option = node("option", null, conditionLabel(condition));
      option.value = condition.id;
      conditionSelect.append(option);
    }
    for (const repeat of repetitions) {
      const option = node("option", null, `Repetition ${repeat} of 3`);
      option.value = String(repeat);
      repeatSelect.append(option);
    }
    conditionSelect.value = state.condition;
    repeatSelect.value = String(state.repeat);
    conditionSelect.addEventListener("change", () => { state.condition = conditionSelect.value; reset(); });
    repeatSelect.addEventListener("change", () => { state.repeat = Number(repeatSelect.value); reset(); });
    for (const [index, stage] of stages.entries()) {
      const item = node("li");
      const button = node("button");
      button.type = "button";
      button.append(node("span", "objection-step-num", index));
      button.append(node("span", "objection-step-name", names[stage]));
      button.addEventListener("click", () => { state.viewStage = index; render(); });
      item.append(button);
      byId("objection-stepper").append(item);
      stepButtons.push(button);
    }
    nextButton.addEventListener("click", () => {
      state.viewStage = Math.min(state.maxRevealed + 1, stages.length - 1);
      state.maxRevealed = Math.max(state.maxRevealed, state.viewStage);
      render();
    });
    resetButton.addEventListener("click", reset);
    const totalCalls = pack.summary?.total_model_calls;
    byId("objection-run-size").textContent = `${pack.exchanges.length} exchanges${Number.isInteger(totalCalls) ? ` · ${totalCalls} AI calls` : ""}`;
    render();
    loading.hidden = true;
    content.hidden = false;
  } catch (reason) {
    fail(reason.message || "rendering failed");
  }
})();
