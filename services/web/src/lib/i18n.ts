// i18next: словари загружаются из API (/api/i18n/<язык>), список языков — по файлам locales/ на сервере.
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

const loaded = new Set<string>();
const missing = new Map<string, Set<string>>();
let flushTimer: number | undefined;

export async function loadLanguage(lng: string) {
  if (!loaded.has(lng)) {
    const r = await fetch(`/api/i18n/${lng}`);
    if (r.ok) {
      i18n.addResourceBundle(lng, "translation", await r.json(), true, true);
      loaded.add(lng);
    }
  }
  await i18n.changeLanguage(lng);
  document.documentElement.lang = lng;
  try { localStorage.setItem("dm_lang", lng); } catch { /* приватный режим */ }
}

/** Язык до входа: последний выбранный в этом браузере или язык браузера, если он есть на сервере. */
export function initialLanguage(): string {
  try { const l = localStorage.getItem("dm_lang"); if (l) return l; } catch { /* ignore */ }
  const nav = (navigator.language || "ru").slice(0, 2);
  return ["ru", "en", "es"].includes(nav) ? nav : "ru";
}

function reportMissing(lng: string, key: string) {
  if (!missing.has(lng)) missing.set(lng, new Set());
  missing.get(lng)!.add(key);
  clearTimeout(flushTimer);
  flushTimer = window.setTimeout(() => {
    for (const [l, keys] of missing) {
      fetch("/api/i18n/missing", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lang: l, keys: [...keys] }) }).catch(() => undefined);
    }
    missing.clear();
  }, 3000);
}

i18n.use(initReactI18next).init({
  lng: "ru",
  fallbackLng: "en",
  resources: {},
  interpolation: { escapeValue: false },
  saveMissing: true,
  missingKeyHandler: (lngs, _ns, key) => reportMissing(lngs[0] || "?", key),
  returnNull: false,
});

export default i18n;

/** Сообщение об ошибке API на языке пользователя. */
export function errText(e: unknown): string {
  const t = i18n.t.bind(i18n);
  if (e && typeof e === "object" && "code" in e) {
    const err = e as { code: string; params?: Record<string, unknown> };
    const code = err.code.split(":")[0];
    return t(code, { ...(err.params || {}), defaultValue: err.code });
  }
  return String(e);
}

export function fmtNum(v: unknown, digits = 1): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (!isFinite(n)) return String(v);
  return n.toLocaleString(i18n.language, { maximumFractionDigits: digits });
}

export function fmtTime(iso: string | null | undefined, tz: string, withDate = false): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(i18n.language, { timeZone: tz, hour: "2-digit", minute: "2-digit",
    ...(withDate ? { day: "2-digit", month: "2-digit" } : {}) });
}
