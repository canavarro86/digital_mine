// В браузере: фильтрация списков «Назначить» по виду работ и машине, допущенные первыми,
// окно «Машина» из модели, редактор смен и графика ВР.
import { expect, test, type Page } from "@playwright/test";

async function login(page: Page, u: string, p: string) {
  await page.goto("/login");
  await page.locator("input").nth(0).fill(u);
  await page.locator("input[type=password]").fill(p);
  await page.locator("button[type=submit]").click();
  await expect(page.locator(".side")).toBeVisible();
}

const options = (page: Page, testid: string) =>
  page.locator(`[data-testid=${testid}] option`).evaluateAll((els) => els.map((e) => ({ text: (e.textContent || "").replace(/^⛔ /, ""), denied: e.className === "denied" })).filter((o) => o.text !== "—"));

test("Назначить: машины и забои фильтруются по виду работ, недопущенные — серым", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, "dispatcher", "ds");
  const token = await page.evaluate(() => localStorage.getItem("dm_token"));
  const h = { Authorization: `Bearer ${token}` };
  const cur = await (await page.request.get("/api/dispatch/order", { headers: h })).json();
  if (!cur.order) await page.request.post("/api/dispatch/order", { headers: h, data: { date: cur.date, shift_no: cur.shift_no } });
  await page.goto("/dispatch");
  await page.getByRole("button", { name: /\+ Назначить/ }).click();
  const work = page.getByTestId("assign-work");

  await work.selectOption("ring_drilling");
  await expect.poll(async () => (await options(page, "assign-face")).some((f) => f.text.startsWith("Камера"))).toBe(true);
  const mach = await options(page, "assign-machine");
  expect(mach.length).toBeGreaterThan(0);
  expect(mach.every((m) => m.text.includes("Simba"))).toBe(true);
  const faces = await options(page, "assign-face");
  expect(faces.every((f) => f.text.startsWith("Камера"))).toBe(true);
  expect(faces.some((f) => /восходящие \(из БДО/.test(f.text))).toBe(true);
  expect(faces.some((f) => /нисходящие \(из БДО/.test(f.text))).toBe(true);
  // выбранная Simba сбрасывается при смене вида работ на проходку
  await page.getByTestId("assign-machine").selectOption({ label: mach.find((m) => !m.denied)!.text });
  await work.selectOption("drilling");
  await expect(page.getByTestId("assign-machine")).toHaveValue("");
  await expect.poll(async () => (await options(page, "assign-face")).some((f) => f.text.startsWith("ПШ"))).toBe(true);
  expect((await options(page, "assign-face")).some((f) => f.text.startsWith("Камера"))).toBe(false);
  expect((await options(page, "assign-machine")).every((m) => !m.text.includes("Simba"))).toBe(true);

  // люди: после выбора буровой допущенные — первыми, недопущенные — серым и после них
  const rig = (await options(page, "assign-machine")).find((m) => !m.denied)!;
  await page.getByTestId("assign-machine").selectOption({ label: rig.text });
  await expect.poll(async () => (await options(page, "assign-person")).some((p) => p.denied)).toBe(true);
  const people = await options(page, "assign-person");
  const firstDenied = people.findIndex((p) => p.denied);
  expect(firstDenied).toBeGreaterThan(0);
  expect(people.slice(firstDenied).every((p) => p.denied)).toBe(true);
  expect(errors).toEqual([]);
});

test("Флот: машина из модели получает параметры и название", async ({ page }) => {
  await login(page, "engineer", "en");
  await page.goto("/fleet");
  await page.getByRole("button", { name: /Добавить машину/ }).click();
  await page.getByTestId("machine-model").selectOption({ label: "Sandvik Axera DD421" });
  await page.getByTestId("machine-number").fill("4801");
  await expect(page.getByTestId("machine-name")).toHaveValue("Axera №4801");
  await expect(page.getByTestId("param-max_length")).toBeVisible();
  await page.goto("/migration");
  await expect(page.locator("h1")).toContainText("Перенос данных");
});

test("Смены: автозаполнение, разрыв подсвечивается, «Сохранить» неактивна", async ({ page }) => {
  await login(page, "admin", "as");
  await page.goto("/mine");
  await page.getByTestId("shift-count").selectOption("3");
  const rows = page.getByTestId("shift-table").locator("tbody tr");
  await expect(rows).toHaveCount(3);
  await expect(page.getByTestId("blast-table").locator("tbody tr")).toHaveCount(3);
  const save = page.getByRole("button", { name: "Сохранить" });
  await expect(save).toBeEnabled();
  const [h, m] = (await rows.nth(0).locator("input").nth(1).inputValue()).split(":").map(Number);
  const later = h * 60 + m + 30;  // смена 2 начинается на 30 мин позже конца смены 1
  await rows.nth(1).locator("input").nth(0).fill(`${String(Math.floor(later / 60) % 24).padStart(2, "0")}:${String(later % 60).padStart(2, "0")}`);
  await expect(page.getByTestId("shift-issues")).toContainText("не покрыто 30 мин");
  await expect(rows.nth(1).locator("input").nth(0)).toHaveClass(/invalid/);
  await expect(save).toBeDisabled();
});
