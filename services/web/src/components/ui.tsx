import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { errText } from "../lib/i18n";

export function Page({ title, actions, children }: { title: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <div>
      <div className="page-head"><h1>{title}</h1><div className="actions">{actions}</div></div>
      {children}
    </div>
  );
}

export function Card({ title, children, actions }: { title?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="card">
      {(title || actions) && <div className="row" style={{ marginBottom: 8 }}><h3 style={{ margin: 0 }}>{title}</h3><div style={{ marginLeft: "auto" }} className="row">{actions}</div></div>}
      {children}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="error">{errText(error)}</div>;
}

export interface Col<T> { key: string; title: ReactNode; render?: (row: T) => ReactNode; num?: boolean }

export function Table<T extends Record<string, any>>({ cols, rows, onRow, empty }: {
  cols: Col<T>[]; rows: T[] | null | undefined; onRow?: (r: T) => void; empty?: ReactNode;
}) {
  const { t } = useTranslation();
  if (!rows) return <div className="muted">{t("common.loading")}</div>;
  if (!rows.length) return <div className="muted">{empty ?? t("common.empty")}</div>;
  return (
    <div className="tbl-wrap">
      <table className="t">
        <thead><tr>{cols.map((c) => <th key={c.key} className={c.num ? "right" : ""}>{c.title}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={(r.id as string) ?? i} onClick={onRow ? () => onRow(r) : undefined} style={onRow ? { cursor: "pointer" } : undefined}>
              {cols.map((c) => <td key={c.key} className={c.num ? "num" : ""}>{c.render ? c.render(r) : fmt(r[c.key])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function fmt(v: unknown): ReactNode {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return Number.isInteger(v) ? v : v.toFixed(2);
  if (typeof v === "boolean") return v ? "✓" : "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function Modal({ title, onClose, children, footer, wide }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={wide ? { width: "min(1200px, 97vw)" } : undefined}>
        <div className="row" style={{ marginBottom: 10 }}><h2 style={{ margin: 0 }}>{title}</h2><button className="small" style={{ marginLeft: "auto" }} onClick={onClose}>✕</button></div>
        {children}
        {footer && <div className="foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Field({ label, children }: { label: ReactNode; children: ReactNode }) {
  return <label className="field">{label}{children}</label>;
}

export function Num({ value, onChange, step = "any", ...rest }: { value: any; onChange: (v: number) => void; step?: string; [k: string]: any }) {
  return <input type="number" step={step} value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? (null as unknown as number) : Number(e.target.value))} {...rest} />;
}

const STATUS_CLASS: Record<string, string> = {
  done: "ok", approved: "ok", working: "ok", resolved: "ok", analyzed: "ok", valid: "ok", mined: "ok", ready: "info",
  driving: "warn", review: "warn", drilling: "warn", idle: "warn", expiring: "warn", ack: "warn", active: "warn", warning: "warn",
  repair: "err", maintenance: "err", expired: "err", open: "err", critical: "err", error: "err",
};

export function Badge({ value, group }: { value: string; group?: string }) {
  const { t } = useTranslation();
  if (!value) return null;
  return <span className={`badge ${STATUS_CLASS[value] || ""}`}>{group ? t(`${group}.${value}`, { defaultValue: value }) : value}</span>;
}

export function Tabs({ tabs, value, onChange }: { tabs: [string, ReactNode][]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="tabs">{tabs.map(([k, l]) => <button key={k} className={value === k ? "on" : ""} onClick={() => onChange(k)}>{l}</button>)}</div>
  );
}

export function Stat({ label, value, unit }: { label: ReactNode; value: ReactNode; unit?: string }) {
  return <div className="stat"><div className="v">{value ?? "—"}{unit && <span className="small muted"> {unit}</span>}</div><div className="l">{label}</div></div>;
}

/** Кнопка с выполнением асинхронного действия, блокировкой и показом ошибки. */
export function Action({ onClick, children, className, disabled, confirm }: {
  onClick: () => Promise<unknown> | unknown; children: ReactNode; className?: string; disabled?: boolean; confirm?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  return (
    <span>
      <button className={className} disabled={busy || disabled} onClick={async () => {
        if (confirm && !window.confirm(confirm)) return;
        setBusy(true); setErr(null);
        try { await onClick(); } catch (e) { setErr(e); } finally { setBusy(false); }
      }}>{busy ? "…" : children}</button>
      {!!err && <span className="badge err" style={{ marginLeft: 6 }}>{errText(err)}</span>}
    </span>
  );
}

export function Progress({ value, total }: { value: number; total: number }) {
  const p = total ? Math.min(100, (value / total) * 100) : 0;
  return <div className="bar" title={`${value}/${total}`}><div style={{ width: `${p}%` }} /></div>;
}
