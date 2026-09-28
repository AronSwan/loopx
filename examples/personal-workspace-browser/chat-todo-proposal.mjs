import { openWorkspacePage } from "./scenario-context.mjs";

// An Agent answers with a Todo proposal, the shape its turn prompt asks for.
// In a Goal conversation the proposal must become a typed todo.create preview
// the owner confirms; without a target Goal it must not create anything.
const GOAL_PROMPT = "请给出一个下一步任务建议。";
const MANAGER_PROMPT = "请为全局给出一个任务建议。";
const PROPOSAL_TEXT = "[P1] 核对发布清单并补齐缺失的验证记录";
const proposalAnswer = {
  message: "我找到一个可评审的步骤。",
  proposals: [{ kind: "todo", priority: "P1", rationale: "发布前需要可核对的证据。", text: PROPOSAL_TEXT }],
};

async function waitFor(predicate, message) {
  const deadline = Date.now() + 10_000;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error(message);
    await new Promise((resolveWait) => setTimeout(resolveWait, 50));
  }
}

export const chatTodoProposalScenario = {
  id: "chat-todo-proposal",
  async run({ browser, collectCoverage, url }) {
    const context = await openWorkspacePage(browser, url, { collectCoverage });
    const { api, page } = context;
    api.answerForMessage = (message) => (message === GOAL_PROMPT || message === MANAGER_PROMPT ? proposalAnswer : null);
    const todoPreviews = () => api.actionPreviews.filter((preview) => preview.action_kind === "todo.create"
      && preview.normalized_parameters?.text === PROPOSAL_TEXT);
    const composer = page.getByLabel("向 LoopX 发送消息");
    try {
      // Manager channel: no target Goal, so the proposal cannot become a write.
      await composer.fill(MANAGER_PROMPT);
      await page.getByRole("button", { name: "发送", exact: true }).click();
      await page.getByText("我找到一个可评审的步骤。", { exact: true }).first().waitFor({ state: "visible", timeout: 10_000 });
      await page.waitForTimeout(500);
      if (todoPreviews().length) throw new Error("A manager-channel proposal created a Todo preview without a target Goal");

      const openGoalChat = async () => {
        await page.locator(".personal-goal-link", { hasText: "Product Release" }).click();
        await page.getByRole("navigation", { name: "Goal 视图" }).getByRole("button", { name: /^(Chat|对话)$/ }).click();
      };
      await openGoalChat();
      await composer.fill(GOAL_PROMPT);
      await page.getByRole("button", { name: "发送", exact: true }).click();
      const card = page.locator(".personal-proposal-row", { hasText: PROPOSAL_TEXT });
      await card.waitFor({ state: "visible", timeout: 10_000 });
      await waitFor(() => todoPreviews().length === 1, "The Goal proposal did not create exactly one Todo preview");
      const [preview] = todoPreviews();
      if (preview.normalized_parameters.goal_id !== "product-release" || preview.normalized_parameters.priority !== "P1") {
        throw new Error(`Todo preview lost its Goal or priority: ${JSON.stringify(preview.normalized_parameters)}`);
      }
      if (!String(preview.idempotency_key).startsWith("chat-todo-proposal:")) {
        throw new Error(`Todo preview key is not derived from its Turn: ${preview.idempotency_key}`);
      }
      if (await page.getByRole("dialog").count()) throw new Error("A proposal card opened the drawer without the owner asking");

      await page.reload({ waitUntil: "networkidle" });
      await page.getByTestId("personal-goal-home").waitFor({ state: "visible" });
      await openGoalChat();
      await card.waitFor({ state: "visible", timeout: 10_000 });

      await card.click();
      await page.getByRole("dialog").getByRole("button", { name: "确认并应用", exact: true }).click();
      await waitFor(() => api.actionApplies.map(decodeURIComponent).includes(preview.proposalId), "Confirming the proposal did not apply its preview");
    } finally {
      await context.close();
    }
    return {
      coverageEntries: context.coverageEntries,
      note: "An Agent Todo proposal becomes a persisted typed preview in its Goal conversation, and none is created without a target Goal.",
    };
  },
};
