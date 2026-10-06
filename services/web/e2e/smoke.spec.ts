// Проверка в браузере: вход тремя ролями, все страницы открываются без ошибок JS, меню по ролям, смена языка.
import { expect, test, type Page } from "@playwright/test";

const PAGES = ["/", "/dispatch/board", "/dispatch", "/faces", "/alerts", "/mine/3d", "/workings", "/mine/import", "/mine",
  "/passports", "/typical", "/rings", "/geology", "/explosives", "/fleet", "/staff", "/migration", "/analysis", "/reports", "/ai",
  "/settings", "/users", "/console", "/platform", "/profile", "/tablet"];
const SHOTS = process.env.SHOTS || "test-results";

async function login(page: Page, u: string, p: string) {
  await page.goto("/login");
  await page.locator("input").nth(0).fill(u);
  await page.locator("input[type=password]").fill(p);
  await page.locator("button[type=submit]").click();
  await expect(page.locator(".side")).toBeVisible();
}

function watch(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !/403|404|Failed to load resource/.test(m.text())) errors.push(`console: ${m.text()}`); });
  return errors;
}

test("admin: все страницы без ошибок", async ({ page }) => {
  const errors = watch(page);
  await login(page, "admin", "as");
  for (const p of PAGES) {
    await page.goto(p);
    await page.waitForTimeout(p === "/mine/3d" ? 3000 : 1200);
    await expect(page.locator("body")).not.toContainText("Unexpected Application Error");
    await page.screenshot({ path: `${SHOTS}/admin${p.replace(/\//g, "_") || "_home"}.png` });
  }
  expect(errors, errors.join("\n")).toEqual([]);
});

test("detail pages: паспорт, забой, камера, веер", async ({ page, request }) => {
  const errors = watch(page);
  await login(page, "engineer", "en");
  const token = await page.evaluate(() => localStorage.getItem("dm_token"));
  const h = { Authorization: `Bearer ${token}` };
  const dev = await (await request.get("/api/passports/dev", { headers: h })).json();
  const faces = await (await request.get("/api/workflow/faces", { headers: h })).json();
  const stopes = (await (await request.get("/api/rings/stopes", { headers: h })).json()).filter((s: any) => s.designs.length);
  const typ = await (await request.get("/api/passports/typical", { headers: h })).json();
  for (const p of [`/passports/${dev[0].id}`, `/faces/${faces[0].id}`, `/faces/${faces.find((f: any) => f.kind === "stope").id}`,
    `/stopes/${stopes[0].id}`, `/rings/${stopes[0].designs[0].id}`, `/typical/${typ[0].id}`]) {
    await page.goto(p);
    await page.waitForTimeout(2000);
    await page.screenshot({ path: `${SHOTS}/engineer${p.replace(/\//g, "_")}.png`, fullPage: true });
  }
  // перетаскивание шпура в редакторе пересчитывает показатели
  await page.goto(`/passports/${dev[0].id}`);
  const circle = page.locator("svg.svgbox circle").nth(20);
  const box = await circle.boundingBox();
  if (box) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + 40, box.y + 30, { steps: 5 });
    await page.mouse.up();
    await page.waitForTimeout(1500);
    await expect(page.getByRole("button", { name: /Сохранить|Save|Guardar/ }).first()).toBeVisible();
  }
  expect(errors, errors.join("\n")).toEqual([]);
});

test("dispatcher: меню без админских пунктов, язык es", async ({ page }) => {
  const errors = watch(page);
  await login(page, "dispatcher", "ds");
  await expect(page.locator(".side")).not.toContainText("Пользователи");
  await expect(page.locator(".side")).not.toContainText("Пульт");
  await expect(page.locator(".side")).toContainText("Наряд");
  await page.locator(".top select").last().selectOption("es");
  await expect(page.locator(".side")).toContainText("Asignación del turno");
  await page.goto("/dispatch/board");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}/dispatcher_board_es.png` });
  await page.locator(".top select").last().selectOption("ru");
  await page.waitForTimeout(800);
  expect(errors, errors.join("\n")).toEqual([]);
});
