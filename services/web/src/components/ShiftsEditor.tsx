// Таблица смен (начало и конец каждой) и график взрывных работ. Покрытие суток проверяет сервер
// (core/shifts.py) — ошибки с точным местом, поле подсвечивается, «Сохранить» неактивна до исправления.
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";
import { Card, Field, Num } from "./ui";

export type ShiftCfg = {
  table: { no: number; start: string; end: string }[];
  blast_windows: { shift: number; start: string; end: string; note?: string }[];
  ventilation_min: number; reentry_min: number; blast_zone: string;
};

/** Текст ошибки проверки смен: длительности уже переведены сервером (minutes_text, missing_text, total_text). */
export function issueText(i: any, t: (k: string, o?: any) => string) {
  return String(t(`errors.${i.code}`, i.params || {}));
}

export default function ShiftsEditor({ value, onChange, onValid }: { value: ShiftCfg; onChange: (v: ShiftCfg) => void; onValid: (ok: boolean) => void }) {
  const { t } = useTranslation();
  const [issues, setIssues] = useState<any[]>([]);
  const [first, setFirst] = useState(value.table[0]?.start || "00:00");
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      try {
        const r = await api.post<{ issues: any[] }>("/api/mine/shifts/validate", value);
        setIssues(r.issues); onValid(!r.issues.length);
      } catch { onValid(false); }
    }, 250);
    return () => window.clearTimeout(timer.current);
  }, [JSON.stringify(value)]);
  const bad = (section: string, row: number, key: string) => issues.some((i) => i.section === section && i.field?.row === row && i.field?.key === key) ? "invalid" : "";
  const fill = async (count: number, start = first) => {
    const r = await api.post<any>("/api/mine/shifts/default", { count, start });
    onChange({ ...value, table: r.table, blast_windows: r.blast_windows.map((w: any) => ({ ...w, note: t("mine.blast_note_default") })) });
  };
  const setRow = (i: number, k: "start" | "end", v: string) => onChange({ ...value, table: value.table.map((r, j) => (j === i ? { ...r, [k]: v } : r)) });
  const setWin = (i: number, patch: any) => onChange({ ...value, blast_windows: value.blast_windows.map((w, j) => (j === i ? { ...w, ...patch } : w)) });
  return (
    <Card title={t("mine.shifts")}>
      <div className="grid g2">
        <div>
          <div className="form">
            <Field label={t("mine.shift_count")}>
              <select data-testid="shift-count" value={value.table.length} onChange={(e) => fill(Number(e.target.value))}>
                {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}</select>
            </Field>
            <Field label={<span>{t("mine.shift_first_start")} <span className="hint" title={t("mine.shift_autofill_hint")}>?</span></span>}>
              <input type="time" value={first} onChange={(e) => { setFirst(e.target.value); fill(value.table.length, e.target.value); }} /></Field>
          </div>
          <table className="t" data-testid="shift-table">
            <thead><tr><th>{t("mine.shift")}</th><th>{t("mine.start")}</th><th>{t("mine.end")}</th></tr></thead>
            <tbody>{value.table.map((r, i) => <tr key={r.no}>
              <td>{r.no}</td>
              <td><input type="time" className={bad("table", i, "start")} value={r.start} onChange={(e) => setRow(i, "start", e.target.value)} /></td>
              <td><input type="time" className={bad("table", i, "end")} value={r.end} onChange={(e) => setRow(i, "end", e.target.value)} /></td>
            </tr>)}</tbody>
          </table>
          <p className="small muted">{t("mine.shift_rules")}</p>
        </div>
        <div>
          <table className="t" data-testid="blast-table">
            <thead><tr><th>{t("mine.shift")}</th><th>{t("mine.blast_start")}</th><th>{t("mine.blast_end")}</th><th>{t("mine.blast_note")}</th><th /></tr></thead>
            <tbody>{value.blast_windows.map((w, i) => <tr key={i}>
              <td><select className={bad("windows", i, "shift")} value={w.shift} onChange={(e) => setWin(i, { shift: Number(e.target.value) })}>
                {value.table.map((r) => <option key={r.no} value={r.no}>{r.no}</option>)}</select></td>
              <td><input type="time" className={bad("windows", i, "start")} value={w.start} onChange={(e) => setWin(i, { start: e.target.value })} /></td>
              <td><input type="time" className={bad("windows", i, "start")} value={w.end} onChange={(e) => setWin(i, { end: e.target.value })} /></td>
              <td><input value={w.note === "blast_vent" ? t("mine.blast_note_default") : w.note || ""} onChange={(e) => setWin(i, { note: e.target.value })} /></td>
              <td><button className="small" onClick={() => onChange({ ...value, blast_windows: value.blast_windows.filter((_, j) => j !== i) })}>✕</button></td>
            </tr>)}</tbody>
          </table>
          <button className="small" onClick={() => { const r = value.table[0]; onChange({ ...value, blast_windows: [...value.blast_windows, { shift: r.no, start: r.start, end: r.start, note: t("mine.blast_note_default") }] }); }}>+ {t("mine.blast_add")}</button>
          <p className="small muted">{t("mine.blast_rules")}</p>
          <div className="form">
            <Field label={`${t("mine.ventilation_min")}, ${t("units.min")}`}><Num value={value.ventilation_min} step="1" onChange={(v) => onChange({ ...value, ventilation_min: v })} /></Field>
            <Field label={<span>{t("mine.reentry_min")}, {t("units.min")} <span className="hint" title={t("mine.reentry_hint")}>?</span></span>}>
              <Num value={value.reentry_min} step="1" onChange={(v) => onChange({ ...value, reentry_min: v })} /></Field>
            <Field label={<span>{t("mine.blast_zone")} <span className="hint" title={t("mine.blast_zone_hint")}>?</span></span>}>
              <select value={value.blast_zone} onChange={(e) => onChange({ ...value, blast_zone: e.target.value })}>
                {["mine", "level", "faces"].map((z) => <option key={z} value={z} disabled={z !== "mine"}>{t(`mine.blast_zones.${z}`)}{z !== "mine" ? ` (${t("mine.later")})` : ""}</option>)}</select></Field>
          </div>
        </div>
      </div>
      {issues.length > 0 && <div className="error" data-testid="shift-issues">{issues.map((i, k) => <div key={k}>{issueText(i, t)}</div>)}</div>}
    </Card>
  );
}
