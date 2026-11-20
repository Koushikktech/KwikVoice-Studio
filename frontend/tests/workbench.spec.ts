import { expect, test } from "@playwright/test";

test("compile editable data, repair a failed scenario and carry the template to the next merchant", async ({ page }) => {
  const initialCompile = page.waitForResponse((response) => response.url().endsWith("/api/compile"));
  await page.goto("/");
  const sessionId = (await (await initialCompile).json()).session_id;
  await expect(page.getByRole("heading", { name: "KwikVoice" })).toBeVisible();
  await page.getByText("Merchant and prompt", { exact: true }).click();
  await expect(page.getByLabel("Compiled prices")).toContainText("₹749");
  await expect(page.getByLabel("Compiled prices")).toContainText("₹629");
  await expect(page.getByLabel("Compiled prices")).toContainText("₹120");
  const cart = page.getByLabel("Cart JSON");
  await expect(cart).toBeEditable();
  const original = await cart.inputValue();
  const changed = JSON.parse(original);
  changed.cod_fee = "55.00";
  await cart.fill(JSON.stringify(changed, null, 2));
  await page.getByRole("button", { name: "Compile inputs" }).click();
  await expect(page.getByLabel("Compiled prices")).toContainText("₹754");

  await page.getByText("Test conversations", { exact: true }).click();
  await page.getByRole("button", { name: "Run all five" }).click();
  await expect(page.getByText("4 / 5", { exact: true })).toBeVisible();
  await expect(page.getByText("26 words", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Propose edit" }).click();
  await expect(page.getByLabel("Unified prompt diff")).toContainText("templates/base.jinja");
  await page.getByRole("button", { name: "Apply to session" }).click();
  await page.getByRole("button", { name: "Rerun failed (1)" }).click();
  await expect(page.getByText("5 / 5", { exact: true })).toBeVisible();
  await expect(page.getByText("Last run tested 1 shopper.", { exact: true })).toBeVisible();

  const newCompile = page.waitForResponse((response) => response.url().endsWith("/api/compile"));
  await page.getByRole("combobox", { name: "Merchant", exact: true }).selectOption("kicksdrop");
  const response = await newCompile;
  expect(response.request().postDataJSON().session_id).toBe(sessionId);
  await expect(page.getByLabel("Editable active prompt")).toHaveValue(/KicksDrop/);
  await expect(page.getByLabel("Editable active prompt")).toHaveValue(/I can confirm the total and help with your checkout\./);
  await expect(page.getByText("No speech issues found.")).toBeVisible();
});

test("no-mic replay and text actions show an approved mock checkout", async ({ page }) => {
  // Exercise replay's transcript fallback without relying on system voice packages.
  await page.addInitScript(() => {
    Object.defineProperty(window, "speechSynthesis", { configurable: true, value: undefined });
    Object.defineProperty(window, "SpeechSynthesisUtterance", { configurable: true, value: undefined });
  });
  await page.goto("/?view=studio");
  await page.getByLabel("Call mode").selectOption("replay");
  await page.getByRole("button", { name: "Play mock call" }).click();
  await expect(page.getByRole("button", { name: "Open mock checkout" })).toBeVisible();
  await page.getByRole("button", { name: "Open mock checkout" }).click();
  await expect(page.getByRole("dialog")).toContainText("₹629");
  await page.getByRole("button", { name: "Close mock checkout" }).click();
  await expect(page.getByText("Ended", { exact: true })).toBeVisible();
  await page.getByLabel("Call mode").selectOption("text");
  await page.getByRole("button", { name: "Start text call" }).click();
  const caller = page.getByLabel("Caller message");
  await caller.fill("Yes, send me the UPI link.");
  await caller.press("Enter");
  await expect(page.getByText("Your mock checkout link is ready.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Open mock checkout" })).toBeVisible();
  await page.getByRole("button", { name: "End call" }).click();
});

test("narrow viewport fits the call and both expandable sections with keyboard navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to workbench" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
  await expect(page.getByLabel("Call mode")).toHaveValue("recorded");
  await expect(page.getByLabel("Cart JSON")).toBeHidden();
  for (const name of ["Merchant and prompt", "Test conversations"]) {
    const section = page.getByText(name, { exact: true });
    await section.focus();
    await page.keyboard.press("Enter");
    await expect(section.locator("..")).toHaveAttribute("open", "");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  }
});
