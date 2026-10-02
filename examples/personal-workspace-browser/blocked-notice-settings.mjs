import { resolve } from "node:path";
import { outputDir } from "./fixture.mjs";
import { openWorkspacePage } from "./scenario-context.mjs";

export const blockedNoticeSettingsScenario = {
  id: "blocked-notice-settings",
  async run({ browser, collectCoverage, url }) {
    const notificationProjection = {
      schema_version: "loopx_goal_channel_notification_projection_v0",
      goals: [{
        goal_id: "product-release", configured: true, enabled: true,
        human_gate_auto_notify_enabled: false, blocked_notice_auto_notify_enabled: false,
        receipt_count: 1,
        blocked_notice_delivery: { delivered_count: 1, unverified_count: 0, resolved_count: 0 },
      }],
    };
    const requests = [];
    const context = await openWorkspacePage(browser, url, {
      collectCoverage,
      apiOptions: { notificationProjection },
      beforeGoto: async (_api, page) => {
        await page.route("**/api/chat/goal-channel/configure", async (route) => {
          const body = route.request().postDataJSON();
          requests.push(body);
          notificationProjection.goals[0].blocked_notice_auto_notify_enabled = body.auto_notify_blocked_notices === true;
          await route.fulfill({ contentType: "application/json", json: {
            ok: true, status: "configured", public_summary: "updated", readback_verified: true,
          }, status: 200 });
        });
      },
    });
    const { page } = context;
    try {
      await page.getByRole("button", { name: "设置", exact: true }).click();
      await page.getByRole("button", { name: "能力中心", exact: true }).click();
      await page.getByRole("radio", { name: "单个 Goal", exact: true }).check();
      await page.getByRole("combobox", { name: "目标 Goal", exact: true }).selectOption("product-release");
      await page.getByRole("navigation", { name: "Goal 能力目录" })
        .getByRole("button", { name: /飞书事件收件箱/ }).click();
      const toggle = page.getByLabel("任务受阻时推送到此目标群");
      await toggle.waitFor();
      await page.getByText("受阻通知：已核验 1 条，未核验 0 条，已解除 0 条").waitFor();
      await page.screenshot({ path: resolve(outputDir, "blocked-notice-settings.png"), animations: "disabled" });
      await toggle.click();
      if (requests.length !== 1 || requests[0].goal_id !== "product-release"
        || requests[0].auto_notify_blocked_notices !== true
        || "auto_notify_human_gates" in requests[0]) {
        throw new Error(`Blocked notice toggle sent the wrong request: ${JSON.stringify(requests)}`);
      }
      await page.waitForFunction(() => {
        const input = [...document.querySelectorAll("input[type=checkbox]")]
          .find((item) => item.closest("label")?.textContent?.includes("任务受阻时推送到此目标群"));
        return input?.checked === true;
      });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.screenshot({ path: resolve(outputDir, "blocked-notice-settings-mobile.png"), animations: "disabled" });
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) {
        throw new Error("Blocked notice settings overflow the narrow viewport");
      }
      if (context.errors.length) throw new Error(context.errors.join(" | "));
      return { coverageEntries: await context.close(), note: "Goal Channel blocked notice opt-in, readback, and mobile layout verified." };
    } catch (error) { await context.close(); throw error; }
  },
};
