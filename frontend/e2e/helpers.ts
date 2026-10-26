import { expect, type Page } from "@playwright/test";
export const PW = "FoodAgent#2026demo";
export async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.locator('input[autocomplete="email"]').fill(email);
  await page.locator('input[autocomplete="current-password"]').fill(PW);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/login/);
}
