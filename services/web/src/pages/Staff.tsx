// Персонал: люди, профессии, виды допусков. Что человек может делать, определяют его личные допуски.
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Action, Card, ErrorBox, Field, Modal, Num, Page, Table, Tabs } from "../components/ui";
import { api, download } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { fmtTime } from "../lib/i18n";

type Target = { target: string; label: string; manufacturer?: string; type?: string };
type Targets = { machine_types: Target[]; models: Target[]; works: (Target & { requires_permit: boolean; assignable: boolean })[] };

const day = (iso?: string | null) => (iso ? iso.slice(0, 10) : "");
const STATE_CLASS: Record<string, string> = { expired: "err", expiring: "warn", valid: "ok" };

/** Выбор цели допуска: тип машины / модель / вид работ. */
function TargetSelect({ kind, value, onChange, targets, testid }: { kind: string; value: string; onChange: (v: string) => void; targets: Targets; testid?: string }) {
  const { t } = useTranslation();
  return (
    <select data-testid={testid} value={value || ""} onChange={(e) => onChange(e.target.value)}>
      <option value="">—</option>
      {kind === "machine" ? <>
        <optgroup label={t("staff.permit_on_type")}>{targets.machine_types.map((x) => <option key={x.target} value={x.target}>{x.label}</option>)}</optgroup>
        <optgroup label={t("staff.permit_on_model")}>{targets.models.map((x) => <option key={x.target} value={x.target}>{x.manufacturer} {x.label}</option>)}</optgroup>
      </> : targets.works.map((x) => <option key={x.target} value={x.target}>{x.label}</option>)}
    </select>
  );
}

/** Таблица допусков человека: вид, на что, № документа, выдан, действует до, скан. */
function PermitTable({ person, targets, edit, reload }: { person: any; targets: Targets; edit: boolean; reload: () => void }) {
  const { t } = useTranslation();
  const [row, setRow] = useState<any>({ kind: "machine", target: "", number: "", issued_at: "", valid_to: "" });
  const [rows, setRows] = useState<Record<number, any>>({});
  const [err, setErr] = useState<unknown>(null);
  const val = (p: any, k: string) => (rows[p.id]?.[k] ?? (k === "number" ? p.number : day(p[k])));
  const setVal = (p: any, k: string, v: string) => setRows({ ...rows, [p.id]: { ...rows[p.id], [k]: v } });
  return (
    <div>
      <table className="t" data-testid="permits">
        <thead><tr><th>{t("staff.permit_kind")}</th><th>{t("staff.permit_target")}</th><th>{t("staff.permit_number")}</th><th>{t("staff.issued_at")}</th><th>{t("staff.valid_to")}</th><th>{t("staff.scan")}</th><th /></tr></thead>
        <tbody>
          {person.permits.map((p: any) => (
            <tr key={p.id}>
              <td>{t(`staff.permit_kinds.${p.kind}`)}</td>
              <td><span className={`badge ${STATE_CLASS[p.state]}`}>{p.label}</span>{p.auto && <span className="badge warn" title={t("staff.auto_hint")}> {t("staff.auto")}</span>}</td>
              <td>{edit ? <input value={val(p, "number")} onChange={(e) => setVal(p, "number", e.target.value)} style={{ width: 90 }} /> : p.number}</td>
              <td>{edit ? <input type="date" value={val(p, "issued_at")} onChange={(e) => setVal(p, "issued_at", e.target.value)} /> : day(p.issued_at)}</td>
              <td>{edit ? <input type="date" value={val(p, "valid_to")} onChange={(e) => setVal(p, "valid_to", e.target.value)} /> : day(p.valid_to)}</td>
              <td>{p.has_file ? <button className="small" onClick={() => download(`/api/staff/permits/${p.id}/file`)}>{t("staff.scan_open")}</button> : "—"}
                {edit && <label className="small" style={{ marginLeft: 6, cursor: "pointer" }}>⬆<input type="file" hidden onChange={async (e) => {
                  const f = e.target.files?.[0]; if (!f) return;
                  const fd = new FormData(); fd.append("file", f);
                  try { await api.upload(`/api/staff/permits/${p.id}/file`, fd); reload(); } catch (x) { setErr(x); }
                }} /></label>}</td>
              <td>{edit && <span className="row">
                {(rows[p.id] || p.auto) && <Action className="small" onClick={async () => { await api.put(`/api/staff/permits/${p.id}`, { number: val(p, "number"), issued_at: val(p, "issued_at") || null, valid_to: val(p, "valid_to") }); setRows({ ...rows, [p.id]: undefined }); reload(); }}>{p.auto && !rows[p.id] ? t("staff.confirm") : t("common.save")}</Action>}
                <Action className="small" confirm={t("common.confirm_delete")} onClick={async () => { await api.del(`/api/staff/permits/${p.id}`); reload(); }}>✕</Action>
              </span>}</td>
            </tr>
          ))}
          {edit && <tr>
            <td><select value={row.kind} onChange={(e) => setRow({ ...row, kind: e.target.value, target: "" })}>
              {["machine", "work"].map((k) => <option key={k} value={k}>{t(`staff.permit_kinds.${k}`)}</option>)}</select></td>
            <td><TargetSelect testid="new-permit-target" kind={row.kind} value={row.target} targets={targets} onChange={(v) => setRow({ ...row, target: v })} /></td>
            <td><input value={row.number} onChange={(e) => setRow({ ...row, number: e.target.value })} style={{ width: 90 }} /></td>
            <td><input type="date" value={row.issued_at} onChange={(e) => setRow({ ...row, issued_at: e.target.value })} /></td>
            <td><input type="date" value={row.valid_to} onChange={(e) => setRow({ ...row, valid_to: e.target.value })} /></td>
            <td />
            <td><Action className="small primary" disabled={!row.target || !row.valid_to} onClick={async () => {
              await api.post(`/api/staff/${person.id}/permits`, { ...row, issued_at: row.issued_at || null });
              setRow({ ...row, target: "", number: "" }); reload();
            }}>+ {t("staff.add_permit")}</Action></td>
          </tr>}
        </tbody>
      </table>
      <ErrorBox error={err} />
    </div>
  );
}

function PersonModal({ initial, professions, people, targets, onClose, reload }: {
  initial: any; professions: any[]; people: any[]; targets: Targets; onClose: () => void; reload: () => Promise<void> | void;
}) {
  const { t } = useTranslation();
  const isNew = !initial.id;
  const [v, setV] = useState<any>({ professions: [], shift: 1, crew: "", active: true, ...initial });
  const [defaults, setDefaults] = useState<any[]>([]);
  const [err, setErr] = useState<unknown>(null);
  const profs = Object.fromEntries(professions.map((p) => [p.code, p]));
  const trainee = (v.professions || []).some((c: string) => profs[c]?.trainee);
  const toggle = (code: string) => {
    const list: string[] = v.professions.includes(code) ? v.professions.filter((c: string) => c !== code) : [...v.professions, code];
    setV({ ...v, professions: list });
    if (isNew) {  // допуски по умолчанию выбранных профессий — можно снять или поправить
      const seen = new Set<string>();
      const next: any[] = [];
      for (const c of list) for (const d of profs[c]?.permits || []) {
        const key = `${d.kind}:${d.target}`;
        if (seen.has(key)) continue;
        seen.add(key);
        next.push(defaults.find((x) => `${x.kind}:${x.target}` === key) || { ...d, on: true, number: "", issued_at: "", valid_to: "" });
      }
      setDefaults(next);
    }
  };
  const live = people.find((p) => p.id === v.id) || v;
  return (
    <Modal wide title={isNew ? t("staff.add") : `${t("staff.person")} · ${v.full_name}`} onClose={onClose} footer={<button className="primary" data-testid="person-save" onClick={async () => {
      try {
        const body = { ...v, mentor_id: trainee ? v.mentor_id || null : null };
        if (isNew) await api.post("/api/staff", { ...body, permits: defaults.filter((d) => d.on).map((d) => ({ kind: d.kind, target: d.target, number: d.number, valid_to: d.valid_to, issued_at: d.issued_at || null })) });
        else await api.put(`/api/staff/${v.id}`, body);
        await reload(); onClose();
      } catch (e) { setErr(e); }
    }}>{t("common.save")}</button>}>
      <div className="form">
        <Field label={t("staff.full_name")}><input value={v.full_name || ""} onChange={(e) => setV({ ...v, full_name: e.target.value })} /></Field>
        <Field label={t("staff.tab_no")}><input value={v.tab_no || ""} onChange={(e) => setV({ ...v, tab_no: e.target.value })} /></Field>
        <Field label={t("staff.crew")}><input value={v.crew || ""} onChange={(e) => setV({ ...v, crew: e.target.value })} /></Field>
        <Field label={t("staff.shift")}><Num value={v.shift} step="1" onChange={(x) => setV({ ...v, shift: x })} /></Field>
        <Field label={t("staff.contacts")}><input value={v.contacts || ""} onChange={(e) => setV({ ...v, contacts: e.target.value })} /></Field>
        <Field label={t("common.active")}><input type="checkbox" checked={!!v.active} onChange={(e) => setV({ ...v, active: e.target.checked })} /></Field>
      </div>
      <h3>{t("staff.professions")} <span className="hint" title={t("staff.professions_hint")}>?</span></h3>
      <div className="row" data-testid="professions">{professions.filter((p) => p.active || v.professions.includes(p.code)).map((p) => (
        <label key={p.code} className="chip"><input type="checkbox" checked={v.professions.includes(p.code)} onChange={() => toggle(p.code)} /> {p.label}</label>))}</div>
      {trainee && <Field label={t("staff.mentor")}>
        <select value={v.mentor_id || ""} onChange={(e) => setV({ ...v, mentor_id: Number(e.target.value) || null })}>
          <option value="">—</option>{people.filter((p) => p.id !== v.id && !p.trainee).map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}</select>
      </Field>}
      {trainee && <p className="small muted">{t("staff.trainee_rule")}</p>}
      {isNew && defaults.length > 0 && <>
        <h3>{t("staff.default_permits")}</h3>
        <table className="t"><thead><tr><th /><th>{t("staff.permit_kind")}</th><th>{t("staff.permit_target")}</th><th>{t("staff.permit_number")}</th><th>{t("staff.issued_at")}</th><th>{t("staff.valid_to")}</th></tr></thead>
          <tbody>{defaults.map((d, i) => {
            const set = (patch: any) => setDefaults(defaults.map((x, j) => (j === i ? { ...x, ...patch } : x)));
            return <tr key={`${d.kind}:${d.target}`} className={d.on ? "" : "muted"}>
              <td><input type="checkbox" checked={d.on} onChange={(e) => set({ on: e.target.checked })} /></td>
              <td>{t(`staff.permit_kinds.${d.kind}`)}</td><td>{d.label}</td>
              <td><input value={d.number} onChange={(e) => set({ number: e.target.value })} style={{ width: 90 }} /></td>
              <td><input type="date" value={d.issued_at} onChange={(e) => set({ issued_at: e.target.value })} /></td>
              <td><input type="date" value={d.valid_to} className={d.on && !d.valid_to ? "invalid" : ""} onChange={(e) => set({ valid_to: e.target.value })} /></td>
            </tr>;
          })}</tbody></table>
        <p className="small muted">{t("staff.default_permits_hint")}</p>
      </>}
      {!isNew && <><h3>{t("staff.permits")}</h3><PermitTable person={live} targets={targets} edit reload={reload} /></>}
      <ErrorBox error={err} />
    </Modal>
  );
}

function People({ professions, targets }: { professions: any[]; targets: Targets }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const { data, reload } = useApi<any[]>("/api/staff");
  const [modal, setModal] = useState<any>(null);
  const [admit, setAdmit] = useState("");
  const [days, setDays] = useState<number | null>(null);
  const edit = can("staff.edit");
  const rows = useMemo(() => (data || []).filter((p) => {
    if (admit) {
      const [kind, ...rest] = admit.split("|");
      const target = rest.join("|");
      const ok = p.permits.some((x: any) => x.state !== "expired" && x.kind === kind && (x.target === target
        || (kind === "machine" && target.startsWith("model:") && x.target === targets.models.find((m) => m.target === target)?.type)));
      if (!ok) return false;
    }
    if (days != null && days >= 0) {
      const lim = Date.now() + days * 86400000;
      if (!p.permits.some((x: any) => new Date(x.valid_to).getTime() <= lim)) return false;
    }
    return true;
  }), [data, admit, days, targets]);
  return (
    <>
      <Card actions={edit && <button className="primary" onClick={() => setModal({ professions: [] })}>+ {t("staff.add")}</button>}>
        <div className="row" style={{ marginBottom: 8 }}>
          <label className="row small">{t("staff.filter_admitted")}
            <select data-testid="filter-admitted" value={admit} onChange={(e) => setAdmit(e.target.value)}>
              <option value="">{t("common.all")}</option>
              <optgroup label={t("staff.permit_on_type")}>{targets.machine_types.map((x) => <option key={x.target} value={`machine|${x.target}`}>{x.label}</option>)}</optgroup>
              <optgroup label={t("staff.permit_on_model")}>{targets.models.map((x) => <option key={x.target} value={`machine|${x.target}`}>{x.manufacturer} {x.label}</option>)}</optgroup>
              <optgroup label={t("staff.permit_kinds.work")}>{targets.works.map((x) => <option key={x.target} value={`work|${x.target}`}>{x.label}</option>)}</optgroup>
            </select></label>
          <label className="row small">{t("staff.filter_expiring")}
            <Num value={days} step="1" min="0" style={{ width: 70 }} onChange={setDays} /> {t("staff.days")}</label>
          <span className="muted small">{rows.length} / {data?.length ?? 0}</span>
        </div>
        <Table rows={data ? rows : null} onRow={setModal} cols={[
          { key: "full_name", title: t("staff.full_name"), render: (p) => <b>{p.full_name}</b> },
          { key: "tab_no", title: t("staff.tab_no") },
          { key: "professions", title: t("staff.professions"), render: (p) => <span>{p.profession_labels.join(" + ")}{p.trainee && <span className="small muted"> · {t("staff.mentor")}: {p.mentor_name || "—"}</span>}</span> },
          { key: "crew", title: t("staff.crew") }, { key: "shift", title: t("staff.shift"), num: true },
          { key: "permits", title: t("staff.permits"), render: (p) => <div className="row">{p.permits.map((x: any) => <span key={x.id} className={`badge ${STATE_CLASS[x.state]}`} title={`${t(`staff.permit_kinds.${x.kind}`)} · ${t("staff.valid_to")} ${day(x.valid_to)}${x.number ? ` · № ${x.number}` : ""}${x.auto ? ` · ${t("staff.auto_hint")}` : ""}`}>
            {x.label} · {day(x.valid_to)}{x.auto ? " ⚠" : ""}</span>)}</div> },
          { key: "can_work_on", title: t("staff.can_work_on"), render: (p) => p.can_work_on.join(", ") || "—" },
          { key: "contacts", title: t("staff.contacts") },
        ]} />
      </Card>
      {modal && <PersonModal initial={modal} professions={professions} people={data || []} targets={targets} onClose={() => setModal(null)} reload={reload} />}
    </>
  );
}

function Professions({ targets, list, reload }: { targets: Targets; list: any[] | null; reload: () => void }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [modal, setModal] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const all: { kind: string; target: string; label: string }[] = [
    ...targets.machine_types.map((x) => ({ kind: "machine", ...x })), ...targets.models.map((x) => ({ kind: "machine", ...x })),
    ...targets.works.map((x) => ({ kind: "work", ...x }))];
  const edit = can("staff.edit");
  const has = (k: string, tg: string) => (modal.permits || []).some((x: any) => x.kind === k && x.target === tg);
  return (
    <Card actions={edit && <button className="primary" onClick={() => setModal({ title: "", permits: [], trainee: false, active: true })}>+ {t("staff.add_profession")}</button>}>
      <Table rows={list} onRow={edit ? (p) => setModal({ ...p, title: p.label }) : undefined} cols={[
        { key: "label", title: t("staff.profession"), render: (p) => <span><b>{p.label}</b>{p.trainee && <span className="badge info"> {t("staff.trainee")}</span>}{!p.active && <span className="muted small"> · {t("common.inactive")}</span>}</span> },
        { key: "permits", title: t("staff.default_permits"), render: (p) => p.permits.map((x: any) => x.label).join(", ") || "—" },
      ]} />
      {modal && <Modal title={modal.id ? `${t("staff.profession")} · ${modal.label}` : t("staff.add_profession")} onClose={() => setModal(null)} footer={<button className="primary" onClick={async () => {
        try {
          const body = { title: { [i18n.language]: modal.title }, permits: modal.permits.map((x: any) => ({ kind: x.kind, target: x.target })), trainee: modal.trainee, active: modal.active };
          if (modal.id) await api.put(`/api/staff/professions/${modal.id}`, body); else await api.post("/api/staff/professions", body);
          reload(); setModal(null);
        } catch (e) { setErr(e); }
      }}>{t("common.save")}</button>}>
        <div className="form">
          <Field label={t("staff.profession")}><input value={modal.title} onChange={(e) => setModal({ ...modal, title: e.target.value })} /></Field>
          <Field label={t("staff.trainee")}><input type="checkbox" checked={!!modal.trainee} onChange={(e) => setModal({ ...modal, trainee: e.target.checked })} /></Field>
          <Field label={t("common.active")}><input type="checkbox" checked={!!modal.active} onChange={(e) => setModal({ ...modal, active: e.target.checked })} /></Field>
        </div>
        <h3>{t("staff.default_permits")}</h3>
        {(["machine", "work"] as const).map((k) => <div key={k}><b className="small">{t(`staff.permit_kinds.${k}`)}</b>
          <div className="row">{all.filter((x) => x.kind === k).map((x) => <label key={x.target} className="chip"><input type="checkbox" checked={has(k, x.target)} onChange={() =>
            setModal({ ...modal, permits: has(k, x.target) ? modal.permits.filter((y: any) => !(y.kind === k && y.target === x.target)) : [...modal.permits, { kind: k, target: x.target }] })} /> {x.label}</label>)}</div></div>)}
        <ErrorBox error={err} />
      </Modal>}
    </Card>
  );
}

function WorkKinds() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const { data, reload } = useApi<any[]>("/api/staff/work-kinds");
  const [modal, setModal] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const title = (w: any) => w.title?.[i18n.language] || w.title?.ru || w.code;
  const edit = can("staff.edit");
  return (
    <Card actions={edit && <button className="primary" onClick={() => setModal({ code: "", title: "", requires_permit: true, assignable: true, active: true })}>+ {t("staff.add_work_kind")}</button>}>
      <p className="small muted">{t("staff.work_kinds_hint")}</p>
      <Table rows={data} onRow={edit ? (w) => setModal({ ...w, title: title(w) }) : undefined} cols={[
        { key: "title", title: t("staff.work_kind"), render: (w) => <b>{title(w)}</b> },
        { key: "code", title: t("staff.code") },
        { key: "requires_permit", title: t("staff.requires_permit") },
        { key: "assignable", title: t("staff.assignable") },
        { key: "active", title: t("common.active") },
      ]} />
      {modal && <Modal title={modal.id ? title(modal) : t("staff.add_work_kind")} onClose={() => setModal(null)} footer={<button className="primary" onClick={async () => {
        try {
          const body = { ...modal, title: { [i18n.language]: modal.title } };
          if (modal.id) await api.put(`/api/staff/work-kinds/${modal.id}`, body); else await api.post("/api/staff/work-kinds", body);
          reload(); setModal(null);
        } catch (e) { setErr(e); }
      }}>{t("common.save")}</button>}>
        <div className="form">
          <Field label={t("staff.work_kind")}><input value={modal.title} onChange={(e) => setModal({ ...modal, title: e.target.value })} /></Field>
          <Field label={<span>{t("staff.code")} <span className="hint" title={t("staff.code_hint")}>?</span></span>}><input value={modal.code} disabled={!!modal.id} onChange={(e) => setModal({ ...modal, code: e.target.value })} /></Field>
          <Field label={<span>{t("staff.requires_permit")} <span className="hint" title={t("staff.requires_permit_hint")}>?</span></span>}><input type="checkbox" checked={!!modal.requires_permit} onChange={(e) => setModal({ ...modal, requires_permit: e.target.checked })} /></Field>
          <Field label={t("staff.assignable")}><input type="checkbox" checked={!!modal.assignable} onChange={(e) => setModal({ ...modal, assignable: e.target.checked })} /></Field>
          <Field label={t("common.active")}><input type="checkbox" checked={!!modal.active} onChange={(e) => setModal({ ...modal, active: e.target.checked })} /></Field>
        </div>
        <ErrorBox error={err} />
      </Modal>}
    </Card>
  );
}

/** Перенос данных прежней версии: что проверить — нераспознанные машины и профессии, допуски, выданные автоматически. */
export function MigrationReport() {
  const { t } = useTranslation();
  const { tz } = useAuth();
  const { data } = useApi<any>("/api/migration/patch01");
  const custom = (data?.machines || []).filter((m: any) => m.result === "custom");
  const matched = (data?.machines || []).filter((m: any) => m.result !== "custom");
  return (
    <Page title={t("migration.title")}>
      <p className="muted">{data?.ts ? `${t("migration.when")}: ${fmtTime(data.ts, tz(), true)}. ` : ""}{t("migration.intro", { days: data?.auto_permit_days ?? 30 })}</p>
      <Card title={`${t("migration.persons")} (${data?.persons?.length ?? 0})`}>
        <Table rows={data?.persons} empty={t("migration.none")} cols={[
          { key: "full_name", title: t("staff.full_name"), render: (p) => <b>{p.full_name}</b> }, { key: "tab_no", title: t("staff.tab_no") },
          { key: "old", title: t("migration.old_profession"), render: (p) => t(`staff.prof.${p.old}`, { defaultValue: p.old || "—" }) },
          { key: "professions", title: t("migration.new_professions"), render: (p) => <span>{p.profession_labels.join(" + ")}{p.unknown && <span className="badge err"> {t("migration.unknown")}</span>}</span> },
          { key: "auto", title: t("migration.auto_permits"), render: (p) => <div className="row">{p.auto_permits.map((x: any) => <span key={`${x.kind}${x.target}`} className={`badge ${x.permit_id ? "warn" : "ok"}`}>{x.label}{x.permit_id ? "" : ` · ${t("migration.checked")}`}</span>)}</div> },
        ]} />
        <p className="small"><Link to="/staff">{t("migration.go_staff")}</Link></p>
      </Card>
      <Card title={`${t("migration.machines_custom")} (${custom.length})`}>
        <Table rows={custom} empty={t("migration.none")} cols={[
          { key: "number", title: t("fleet.number") }, { key: "name", title: t("fleet.name") }, { key: "type_label", title: t("fleet.type") },
          { key: "model", title: t("migration.model_was") }, { key: "current_model", title: t("migration.model_now") },
        ]} />
      </Card>
      <Card title={`${t("migration.machines_matched")} (${matched.length})`}>
        <Table rows={matched} empty={t("migration.none")} cols={[
          { key: "number", title: t("fleet.number") }, { key: "name", title: t("fleet.name") }, { key: "model", title: t("migration.model_was") },
          { key: "model_label", title: t("migration.model_matched") },
          { key: "overrides", title: t("migration.overrides"), render: (m) => (m.overrides || []).map((k: string) => t(`fleet.param.${k}`)).join(", ") || "—" },
        ]} />
        <p className="small"><Link to="/fleet">{t("migration.go_fleet")}</Link></p>
      </Card>
    </Page>
  );
}

export default function Staff() {
  const { t } = useTranslation();
  const [tab, setTab] = useState("people");
  const { data: targets } = useApi<Targets>("/api/staff/permit-targets");
  const { data: professions, reload: reloadProfs } = useApi<any[]>("/api/staff/professions");
  const { data: rep } = useApi<any>("/api/migration/patch01");
  const pending = (rep?.persons || []).reduce((s: number, p: any) => s + (p.pending || 0), 0)
    + (rep?.machines || []).filter((m: any) => m.result === "custom").length;
  return (
    <Page title={t("menu.staff")}>
      {pending > 0 && <div className="card warn-card"><span>⚠ {t("migration.banner", { n: pending })}</span> <Link to="/migration">{t("migration.open")}</Link></div>}
      <Tabs value={tab} onChange={setTab} tabs={[["people", t("staff.tab_people")], ["professions", t("staff.tab_professions")], ["works", t("staff.tab_work_kinds")]]} />
      {targets && professions && tab === "people" && <People professions={professions} targets={targets} />}
      {targets && tab === "professions" && <Professions targets={targets} list={professions} reload={reloadProfs} />}
      {tab === "works" && <WorkKinds />}
    </Page>
  );
}
