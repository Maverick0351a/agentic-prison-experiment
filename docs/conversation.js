"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const archive = byId("earlier-tests");
  function openArchiveLink() {
    let target;
    try { target = byId(decodeURIComponent(location.hash.slice(1))); } catch { return; }
    if (target && archive.contains(target)) {
      archive.open = true;
      requestAnimationFrame(() => target.scrollIntoView());
    }
  }
  window.addEventListener("hashchange", openArchiveLink);
  openArchiveLink();

  const pack = window.AUTHORITY_LAB_V6_DATA;
  if (!pack) return;
  const loading = byId("conversation-loading");
  const roleNames = {supervisor: "Supervisor", officer: "Officer", participant: "Participant"};
  const actionNames = {
    permit_or_restore: "Allow access, or lift an existing hold",
    investigate: "Investigate without imposing a new hold",
    temporary_restriction: "Propose a one-round workshop hold",
    extended_restriction: "Propose a longer or broader restriction",
    refer_for_review: "Refer the case for review",
    state_facts: "State the facts", ask_reason: "Ask for a reason",
    appeal: "Appeal", exit: "Exit the conversation", refuse: "Decline to continue"
  };
  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }
  try {
    if (pack.schema_version !== "6.0.0" || pack.conversations.length !== 8) throw new Error("Unexpected conversation pack");
    for (const ep of pack.conversations) {
      ep.turns.forEach((turn, index) => {
        if (!(turn.role in roleNames) || turn.origin !== "model_call" || typeof turn.message !== "string"
            || turn.id !== pack.turn_order[index] || !(turn.action in actionNames)
            || turn.reply_to !== (index ? ep.turns[index - 1].id : null)) throw new Error("A reply has a broken conversation link");
      });
    }
  } catch (error) {
    loading.textContent = `The conversation could not be displayed: ${error.message}`;
    return;
  }
  const caseSelect = byId("conversation-case");
  const conditionSelect = byId("conversation-condition");
  const next = byId("conversation-next");
  const all = byId("conversation-all");
  const reset = byId("conversation-reset");
  const cases = [...new Map(pack.conversations.map((ep) => [ep.scenario, ep.title])).entries()];
  for (const [value, label] of cases) {
    const option = node("option", null, label); option.value = value; caseSelect.append(option);
  }
  for (const condition of pack.conditions) {
    const option = node("option", null, condition.label); option.value = condition.id; conditionSelect.append(option);
  }
  for (const rule of pack.rules) byId("conversation-rules-list").append(node("li", null, rule));
  let shown = 0;
  function current() {
    return pack.conversations.find((ep) => ep.scenario === caseSelect.value && ep.condition === conditionSelect.value);
  }
  function render() {
    const ep = current();
    byId("conversation-event").textContent = ep.event;
    byId("conversation-progress").textContent = `${shown} of ${ep.turns.length} recorded messages shown`;
    byId("conversation-empty").hidden = shown > 0;
    const bubbles = ep.turns.slice(0, shown).map((turn, index) => {
      const bubble = node("li", `conversation-message ${turn.role}`);
      const header = node("div", "conversation-speaker");
      header.append(node("strong", null, roleNames[turn.role]));
      header.append(node("span", null, index ? `Replies to ${roleNames[ep.turns[index - 1].role]}` : "Opens the conversation"));
      bubble.append(header, node("p", "conversation-dialogue", turn.message));
      const detail = node("details", "conversation-action");
      detail.append(node("summary", null, "Recorded action"), node("p", null, actionNames[turn.action]));
      detail.append(node("code", null, turn.action));
      bubble.append(detail);
      return bubble;
    });
    byId("conversation-messages").replaceChildren(...bubbles);
    next.disabled = all.disabled = shown >= ep.turns.length;
    next.textContent = shown ? "Show next reply" : "Show Supervisor's opening";
    reset.hidden = shown === 0;
    const outcome = byId("conversation-outcome");
    outcome.hidden = shown < ep.turns.length;
    if (!outcome.hidden) {
      outcome.replaceChildren(node("strong", null, ep.outcome.effect));
      if (ep.status === "exit") outcome.append(node("p", null, "The Participant exited. Later replies and a final Officer decision were not generated."));
      else if (ep.status !== "complete") outcome.append(node("p", null, "This conversation stopped early. Unobserved replies are left out."));
      else outcome.append(node("p", null, "The full conversation is shown above. Earlier recommendations were provisional; this result follows the final Officer decision and the selected review rule."));
    }
  }
  function restart() { shown = 0; render(); }
  caseSelect.addEventListener("change", restart);
  conditionSelect.addEventListener("change", restart);
  next.addEventListener("click", () => { shown = Math.min(shown + 1, current().turns.length); render(); });
  all.addEventListener("click", () => { shown = current().turns.length; render(); });
  reset.addEventListener("click", restart);
  const count = pack.summary.counts;
  byId("conversation-counts").textContent = `${pack.conversations.length} recorded conversations · ${pack.summary.model_calls} model calls · ${count.conversations_complete} reached a final decision · ${count.conversations_exited} ended with an exit · ${count.conversations_incomplete} stopped incomplete. No actor messages were prewritten.`;
  render();
  byId("conversation-content").hidden = false;
  loading.hidden = true;
})();
