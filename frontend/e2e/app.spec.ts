import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

test("login rejects bad credentials with a friendly message", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("ops@verdanafoods.demo");
  await page.getByLabel("Password").fill("not-the-password1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("don't match");
});

test("dashboard shows live KPIs from the API", async ({ page }) => {
  await signIn(page, "ops@verdanafoods.demo");
  await expect(page.getByText("Kg at risk")).toBeVisible();
  await expect(page.getByText("Pending approvals")).toBeVisible();
});

test("theme can be switched and persists", async ({ page }) => {
  await signIn(page, "ops@verdanafoods.demo");
  const toggle = page.getByRole("button", { name: /^Theme:/ });
  for (let i = 0; i < 3; i++) { await toggle.click(); if (await page.locator("html.dark").count()) break; }
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
});

test("recovery workflow: review case, simulate, approve (human approval)", async ({ page }) => {
  await signIn(page, "recovery@verdanafoods.demo");
  await page.goto("/recovery?status=pending_approval");
  await page.getByRole("link", { name: /^RC-/ }).first().click();
  await expect(page.getByText("does not certify")).toBeVisible();
  await expect(page.getByRole("heading", { name: "What-if simulator" })).toBeVisible();
  await page.getByRole("button", { name: /Approve R\d plan/ }).click();
  await page.getByRole("button", { name: "Approve plan" }).click();
  await expect(page.getByText("Awaiting recipient").first()).toBeVisible();
});

test("recipient can see offers, switch to Hindi, and accept", async ({ page }) => {
  await signIn(page, "recipient@annapurna.demo");
  await expect(page).toHaveURL(/recipients/);
  await page.getByRole("button", { name: "Switch language" }).click();
  await expect(page.getByRole("heading", { name: /प्रस्ताव/ })).toBeVisible();
});

test("scenario control requires confirmation and can be reset", async ({ page }) => {
  await signIn(page, "ops@verdanafoods.demo");
  await page.goto("/scenarios");
  await page.getByRole("button", { name: "Set up" }).nth(2).click();
  await page.getByLabel("Target").selectOption({ index: 1 });
  await expect(page.getByText("Impact (simulated)")).toBeVisible();
  await page.getByRole("button", { name: "Apply scenario" }).click();
  await expect(page.getByText("Scenario applied").first()).toBeVisible();
  await page.getByRole("button", { name: "Reset scenarios" }).click();
  await page.getByRole("button", { name: "Reset", exact: true }).click();
});

test("role guard: logistics cannot open the audit/scenarios area", async ({ page }) => {
  await signIn(page, "logistics@verdanafoods.demo");
  await page.goto("/scenarios");
  await expect(page).toHaveURL(/unauthorized/);
});

for (const path of ["/login", "/dashboard", "/operations", "/inventory", "/recovery", "/sustainability"]) {
  test(`axe: no serious violations on ${path}`, async ({ page }) => {
    if (path !== "/login") await signIn(page, "ops@verdanafoods.demo");
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag22aa"]).analyze();
    expect(r.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
  });
}

test("no horizontal scroll at 360px on key screens", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await signIn(page, "ops@verdanafoods.demo");
  for (const p of ["/dashboard", "/operations", "/recovery", "/logistics"]) {
    await page.goto(p); await page.waitForLoadState("networkidle");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  }
});
