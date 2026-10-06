import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Action, Badge, Card, ErrorBox, Field, Modal, Page, Table } from "../components/ui";
import { api, qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { errText, fmtTime } from "../lib/i18n";

function Issues({ issues }: { issues: any[] }) {
  const { t } = useTranslation();
  if (!issues?.length) return <Badge value="ok" />;
  return <div>{issues.map((i, k) => <div key={k}><span className={`badge ${i.level === "error" ? "err" : "warn"}`}>{String(t(`errors.${i.code}`, i.params || {}))}</span></div>)}</div>;
}

/** Список с допущенными первыми; недопущенные — серым, причина при наведении и под списком. */
function PickList({ testid, value, items, label, onChange }: { testid: string; value: number | null; items: any[] | undefined; label: (x: any) => string; onChange: (id: number | null) => void }) {
  const { t } = useTranslation();
  const sel = (items || []).find((x) => x.id === value);
  return (
    <>
      <select data-testid={testid} value={value || ""} className={sel && !sel.ok ? "invalid" : ""} onChange={(e) => onChange(Number(e.target.value) || null)}>
        <option value="">—</option>
        {(items || []).map((x) => <option key={x.id} value={x.id} className={x.ok ? "" : "denied"} title={x.reasons.join("\n")}>{x.ok ? "" : "⛔ "}{label(x)}</option>)}
      </select>
      {sel && !sel.ok && <span className="small" style={{ color: "#9b1c1c" }}>{sel.reasons.join("; ")}</span>}
      {!sel && items && <span className="small muted">{t("dispatch.admitted_count", { n: items.filter((x) => x.ok).length, total: items.length })}</span>}
    </>
  );
}

function AssignForm({ order, workTypes, onDone, initial }: { order: any; workTypes: string[]; onDone: () => void; initial?: any }) {
  const { t } = useTranslation();
  const { data: targets } = useApi<any>("/api/staff/permit-targets");
  const [f, setF] = useState<any>(initial || { work_type: "drilling" });
  const { data: cand } = useApi<any>("/api/dispatch/candidates" + qs({ work_type: f.work_type, order_id: order.id, machine_id: f.machine_id, person_id: f.person_id, assignment_id: initial?.assignment_id }), 0, [f.work_type, f.machine_id, f.person_id]);
  const [check, setCheck] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  // несовместимые с видом работ и машиной забой и машина сбрасываются
  useEffect(() => {
    if (!cand) return;
    const patch: any = {};
    if (f.machine_id && !cand.machines.some((m: any) => m.id === f.machine_id)) patch.machine_id = null;
    if (f.face_id && !cand.faces.some((x: any) => x.face_id === f.face_id && (x.direction ?? null) === (f.direction ?? null))) { patch.face_id = null; patch.direction = null; }
    if (Object.keys(patch).length) setF({ ...f, ...patch });
  }, [cand]);
  useEffect(() => {
    if (!f.person_id && !f.machine_id && !f.face_id) return;
    api.post("/api/dispatch/check", { ...f, order_id: order.id, assignment_id: initial?.assignment_id }).then(setCheck).catch(() => undefined);
  }, [f.person_id, f.machine_id, f.face_id, f.work_type, f.direction]);
  const workLabel = (w: string) => t(`dispatch.work.${w}`, { defaultValue: (targets?.works || []).find((x: any) => x.target === w)?.label || w });
  return (
    <div>
      <div className="form">
        <Field label={t("dispatch.work_type")}>
          <select data-testid="assign-work" value={f.work_type} onChange={(e) => setF({ ...f, work_type: e.target.value })}>
            {workTypes.map((w) => <option key={w} value={w}>{workLabel(w)}</option>)}
          </select>
        </Field>
        <Field label={t("board.machine")}>
          <PickList testid="assign-machine" value={f.machine_id} items={cand?.machines} label={(m) => `${m.label} · ${m.model} · ${t(`fleet.status.${m.status}`)}`} onChange={(id) => setF({ ...f, machine_id: id })} />
        </Field>
        <Field label={t("board.person")}>
          <PickList testid="assign-person" value={f.person_id} items={cand?.persons} label={(p) => `${p.full_name} · ${p.professions.join(" + ")}`} onChange={(id) => setF({ ...f, person_id: id })} />
        </Field>
        <Field label={f.work_type === "ring_drilling" ? t("dispatch.face_or_stope") : t("board.face")}>
          <PickList testid="assign-face" value={(cand?.faces || []).findIndex((x: any) => x.face_id === f.face_id && (x.direction ?? null) === (f.direction ?? null)) + 1 || null}
            items={(cand?.faces || []).map((x: any, i: number) => ({ ...x, id: i + 1 }))}
            label={(x) => `${x.label} · ${t(`workflow.status.${x.status}`)}`}
            onChange={(i) => { const x = i ? cand.faces[i - 1] : null; setF({ ...f, face_id: x?.face_id ?? null, direction: x?.direction ?? null }); }} />
        </Field>
      </div>
      {check && <div style={{ marginTop: 10 }} data-testid="assign-checks">
        <b>{t("dispatch.checks")}:</b> <Issues issues={check.issues} />
        {check.suggestions?.persons && <div className="small">{t("dispatch.suggest_person")}: {check.suggestions.persons.map((p: any) => <button key={p.id} className="small" onClick={() => setF({ ...f, person_id: p.id })}>{p.full_name}</button>)}</div>}
        {check.suggestions?.machines && <div className="small">{t("dispatch.suggest_machine")}: {check.suggestions.machines.map((m: any) => <button key={m.id} className="small" onClick={() => setF({ ...f, machine_id: m.id })}>{m.number}</button>)}</div>}
      </div>}
      <ErrorBox error={err} />
      <div className="foot" style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
        {initial?.assignment_id && <input placeholder={t("dispatch.reason")} value={f.reason || ""} onChange={(e) => setF({ ...f, reason: e.target.value })} />}
        <button className="primary" data-testid="assign-submit" onClick={async () => {
          try {
            if (initial?.assignment_id) await api.post("/api/dispatch/reassign", { ...f, assignment_id: initial.assignment_id });
            else await api.post(`/api/dispatch/order/${order.id}/assign`, f);
            onDone();
          } catch (e) { setErr(e); }
        }}>{initial?.assignment_id ? t("dispatch.reassign") : t("dispatch.assign")}</button>
      </div>
    </div>
  );
}

export default function Dispatch() {
  const { t } = useTranslation();
  const { can, tz } = useAuth();
  const [sel, setSel] = useState<{ date?: string; shift_no?: number }>({});
  const { data, reload, error } = useApi<any>("/api/dispatch/order" + qs(sel), 15000, [sel.date, sel.shift_no]);
  const { data: hist, reload: reloadHist } = useApi<any[]>("/api/dispatch/reassignments?limit=30", 30000);
  const [modal, setModal] = useState<any>(null);
  const edit = can("dispatch.edit");
  const order = data?.order;
  const [copyRes, setCopyRes] = useState<any>(null);
  const { data: clock } = useApi<any>("/api/clock", 30000);
  const { data: shiftsCfg } = useApi<any>("/api/mine/shifts");
  const done = () => { setModal(null); reload(); reloadHist(); };
  const create = async (copy?: string) => { const r = await api.post("/api/dispatch/order", { date: data.date, shift_no: data.shift_no, copy }); setCopyRes(copy ? r : null); reload(); };
  return (
    <Page title={t("menu.dispatch")} actions={<>
      <input type="date" value={data?.date || ""} onChange={(e) => setSel({ ...sel, date: e.target.value })} />
      <select value={data?.shift_no || 1} onChange={(e) => setSel({ ...sel, date: data?.date, shift_no: Number(e.target.value) })}>
        {(shiftsCfg?.table || [{ no: 1 }, { no: 2 }]).map((r: any) => <option key={r.no} value={r.no}>{t("header.shift", { n: r.no })}{r.start ? ` · ${r.start}–${r.end}` : ""}</option>)}
      </select>
      {data && data.current && (data.date !== data.current.date || data.shift_no !== data.current.shift_no) && <button onClick={() => setSel({})}>{t("dispatch.current")}</button>}
    </>}>
      <ErrorBox error={error} />
      {data && !order && <Card title={t("dispatch.no_order")}>
        {edit ? <div className="row">
          <Action className="primary" onClick={() => create()}>{t("dispatch.create_empty")}</Action>
          <Action onClick={() => create("yesterday")}>{t("dispatch.copy_yesterday")}</Action>
          <Action onClick={() => create("previous")}>{t("dispatch.copy_previous")}</Action>
        </div> : <span className="muted">{t("common.view_only")}</span>}
      </Card>}
      {copyRes && copyRes.skipped?.length > 0 && <Card title={t("dispatch.copy_skipped", { n: copyRes.skipped.length, copied: copyRes.copied })}>
        {copyRes.skipped.map((r: any, i: number) => <div key={i} className="small">{[r.person, r.machine, r.face].filter(Boolean).join(" · ")}: <Issues issues={r.issues} /></div>)}
      </Card>}
      {clock?.blast?.now && data && data.date === data.current?.date && data.shift_no === data.current?.shift_no &&
        <div className="card warn-card" data-testid="blast-now">⛔ {t("dispatch.blast_now", { until: fmtTime(clock.blast.now.end, tz()), reentry: clock.blast.reentry_min })}</div>}
      {order?.coverage?.length > 0 && <div className="card warn-card" data-testid="coverage">⚠ {order.coverage.map((c: any) => t("dispatch.no_admitted", { machine: c.machine, n: c.shift_no })).join("; ")}</div>}
      {order && <Card title={`${t("dispatch.order")} ${order.date} · ${t("header.shift", { n: order.shift_no })} · ${fmtTime(order.start, tz())}–${fmtTime(order.end, tz())}`}
        actions={edit && <button className="primary" onClick={() => setModal({ kind: "new" })}>+ {t("dispatch.assign")}</button>}>
        <Table rows={order.assignments} cols={[
          { key: "person_name", title: t("board.person") },
          { key: "machine_number", title: t("board.machine"), render: (a) => <span>{a.machine_number} {a.machine_status && a.machine_status !== "working" && <Badge value={a.machine_status} group="fleet.status" />}</span> },
          { key: "face_name", title: t("board.face"), render: (a) => <span>{a.face_name} <Badge value={a.face_status} group="workflow.status" /></span> },
          { key: "work_type", title: t("board.work"), render: (a) => t(`dispatch.work.${a.work_type}`, { defaultValue: a.work_label }) },
          { key: "started_at", title: t("dispatch.from"), render: (a) => fmtTime(a.started_at, tz()) },
          { key: "ended_at", title: t("dispatch.to"), render: (a) => a.ended_at ? fmtTime(a.ended_at, tz()) : "" },
          { key: "issues", title: t("dispatch.checks"), render: (a) => a.active ? <Issues issues={a.issues} /> : <span className="muted small">{t("dispatch.replaced")}</span> },
          { key: "act", title: "", render: (a) => edit && a.active ? <span className="row">
            <button className="small" onClick={() => setModal({ kind: "re", a })}>{t("dispatch.reassign")}</button>
            <Action className="small" confirm={t("common.confirm_delete")} onClick={async () => { await api.del(`/api/dispatch/assignments/${a.id}`); reload(); }}>✕</Action>
          </span> : null },
        ]} />
      </Card>}
      <Card title={t("dispatch.history")}>
        <Table rows={hist} cols={[
          { key: "ts", title: t("common.time"), render: (r) => fmtTime(r.ts, tz(), true) },
          { key: "username", title: t("common.user") },
          { key: "change", title: t("dispatch.change"), render: (r) => Object.entries(r.change || {}).map(([k, v]: any) => `${t(`dispatch.fields.${k}`)}: ${v.from ?? "—"} → ${v.to ?? "—"}`).join("; ") },
          { key: "reason", title: t("dispatch.reason") },
        ]} />
      </Card>
      {modal && <Modal title={modal.kind === "new" ? t("dispatch.assign") : t("dispatch.reassign")} onClose={() => setModal(null)}>
        <AssignForm order={order} workTypes={data?.work_types || []} onDone={done} initial={modal.kind === "re" ? { assignment_id: modal.a.id, person_id: modal.a.person_id, machine_id: modal.a.machine_id, face_id: modal.a.face_id, direction: modal.a.direction, work_type: modal.a.work_type } : undefined} />
      </Modal>}
    </Page>
  );
}

export { errText };
