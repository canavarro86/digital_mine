// Флот: машины и справочник моделей. Параметры — с понятными названиями, единицами и подсказками.
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge, Card, ErrorBox, Field, Modal, Num, Page, Table, Tabs } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { fmtNum } from "../lib/i18n";

type Meta = { types: Record<string, { params: string[]; defaults: Record<string, unknown> }>; params: Record<string, { unit?: string; type: string; options?: string[] }> };
const STATUSES = ["working", "idle", "repair", "maintenance"];
const DRILLS = ["dev_drill", "ring_drill"];

/** Название параметра с единицей и подсказкой «?». */
export function ParamLabel({ k, meta }: { k: string; meta: Meta | null }) {
  const { t } = useTranslation();
  const unit = meta?.params[k]?.unit;
  return <span>{t(`fleet.param.${k}`)}{unit ? `, ${t(`units.${unit}`)}` : ""} <span className="hint" title={t(`fleet.hint.${k}`)}>?</span></span>;
}

/** Поля параметров по типу машины; base — значения модели (отличия помечаются, ↺ возвращает значение модели). */
function ParamsForm({ type, meta, value, base, onChange }: {
  type: string; meta: Meta; value: Record<string, any>; base?: Record<string, any> | null; onChange: (v: Record<string, any>) => void;
}) {
  const { t } = useTranslation();
  const keys = meta.types[type]?.params || [];
  return (
    <div className="form">
      {keys.map((k) => {
        const p = meta.params[k] || { type: "num" };
        const changed = !!base && k in base && base[k] !== value[k] && !(value[k] == null && base[k] == null);
        const set = (x: unknown) => onChange({ ...value, [k]: x });
        return <Field key={k} label={<span className={changed ? "changed" : ""} data-testid={`param-${k}`}><ParamLabel k={k} meta={meta} />
          {changed && <> <span className="badge warn" title={`${t("fleet.model_value")}: ${base![k]}`}>{t("fleet.changed")}</span>
            <button type="button" className="small" title={t("fleet.reset_to_model")} onClick={() => set(base![k])}>↺</button></>}</span>}>
          {p.type === "select" ? <select value={value[k] ?? ""} onChange={(e) => set(e.target.value)}>
            <option value="">—</option>{(p.options || []).map((o) => <option key={o} value={o}>{t(`fleet.opt.${o}`)}</option>)}</select>
            : p.type === "text" ? <input value={value[k] ?? ""} onChange={(e) => set(e.target.value)} />
            : <Num value={value[k]} onChange={set} step={p.type === "int" ? "1" : "any"} />}
        </Field>;
      })}
    </div>
  );
}

function autoName(number: string, model: any, typeLabel: string, rawModel = "") {
  const n = (number || "").trim();
  if (!/^[\d\-/.]+$/.test(n)) return n;
  return `${model ? model.short_name || model.model : rawModel.trim().split(/\s+/)[0] || typeLabel} №${n}`;
}

function MachineModal({ initial, meta, models, onClose, onSaved }: { initial: any; meta: Meta; models: any[]; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation();
  const [v, setV] = useState<any>({ ...initial, params: { ...(initial.params || {}) } });
  const [nameTouched, setNameTouched] = useState(!!initial.id && initial.name !== autoName(initial.number, models.find((m) => m.id === initial.model_id), t(`fleet.types.${initial.type}`)));
  const [err, setErr] = useState<unknown>(null);
  const model = models.find((m) => m.id === v.model_id) || null;
  const type = model ? model.type : v.type;
  const update = (patch: any) => {
    const nv = { ...v, ...patch };
    const m = models.find((x) => x.id === nv.model_id) || null;
    if (!nameTouched) nv.name = autoName(nv.number, m, t(`fleet.types.${m ? m.type : nv.type}`), m ? "" : nv.model);
    setV(nv);
  };
  const pickModel = (id: string) => {
    if (id === "custom") return update({ model_id: null, params: { ...(meta.types[v.type]?.defaults || {}), ...v.params } });
    const m = models.find((x) => x.id === Number(id));
    update({ model_id: m.id, type: m.type, model: m.model, manufacturer: m.manufacturer, params: { ...m.params } });
  };
  const byType = useMemo(() => Object.keys(meta.types).map((tp) => [tp, models.filter((m) => m.type === tp && (m.active || m.id === v.model_id))] as const), [models, meta, v.model_id]);
  return (
    <Modal wide title={`${t("fleet.machine")}${v.name ? ` · ${v.name}` : ""}`} onClose={onClose} footer={<button className="primary" onClick={async () => {
      try {
        const body = { ...v, model_id: v.model_id || null, type };
        if (v.id) await api.put(`/api/fleet/${v.id}`, body); else await api.post("/api/fleet", body);
        onSaved(); onClose();
      } catch (e) { setErr(e); }
    }}>{t("common.save")}</button>}>
      <div className="form">
        <Field label={t("fleet.model_pick")}>
          <select data-testid="machine-model" value={v.model_id ?? "custom"} onChange={(e) => pickModel(e.target.value)}>
            <option value="custom">{t("fleet.custom")}</option>
            {byType.map(([tp, list]) => list.length ? <optgroup key={tp} label={t(`fleet.types.${tp}`)}>
              {list.map((m) => <option key={m.id} value={m.id}>{m.manufacturer} {m.label}</option>)}</optgroup> : null)}
          </select>
        </Field>
        {!model && <Field label={t("fleet.type")}>
          <select value={v.type} onChange={(e) => update({ type: e.target.value, params: { ...(meta.types[e.target.value]?.defaults || {}) } })}>
            {Object.keys(meta.types).map((k) => <option key={k} value={k}>{t(`fleet.types.${k}`)}</option>)}</select>
        </Field>}
        {!model && <Field label={t("fleet.manufacturer")}><input value={v.manufacturer || ""} onChange={(e) => update({ manufacturer: e.target.value })} /></Field>}
        {!model && <Field label={t("fleet.model")}><input value={v.model || ""} onChange={(e) => update({ model: e.target.value })} /></Field>}
        <Field label={t("fleet.number")}><input data-testid="machine-number" value={v.number || ""} onChange={(e) => update({ number: e.target.value })} /></Field>
        <Field label={<span>{t("fleet.name")} <span className="hint" title={t("fleet.name_hint")}>?</span></span>}>
          <input data-testid="machine-name" value={v.name || ""} onChange={(e) => { setNameTouched(true); setV({ ...v, name: e.target.value }); }} /></Field>
        <Field label={t("fleet.year")}><Num value={v.year} step="1" onChange={(x) => setV({ ...v, year: x })} /></Field>
        <Field label={t("common.status")}><select value={v.status} onChange={(e) => setV({ ...v, status: e.target.value })}>
          {STATUSES.map((s) => <option key={s} value={s}>{t(`fleet.status.${s}`)}</option>)}</select></Field>
        <Field label={t("fleet.engine_hours")}><Num value={v.engine_hours} onChange={(x) => setV({ ...v, engine_hours: x })} /></Field>
      </div>
      {model?.verify && <p className="small muted">⚠ {t("fleet.verify_note")}</p>}
      <h3>{t("fleet.params")}</h3>
      <ParamsForm type={type} meta={meta} value={v.params} base={model?.params} onChange={(params) => setV({ ...v, params })} />
      <ErrorBox error={err} />
    </Modal>
  );
}

function ModelModal({ initial, meta, onClose, onSaved }: { initial: any; meta: Meta; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation();
  const [v, setV] = useState<any>({ verify: true, active: true, ...initial, params: { ...(initial.params || {}) } });
  const [err, setErr] = useState<unknown>(null);
  return (
    <Modal wide title={initial.id ? `${t("fleet.model_one")} · ${initial.manufacturer} ${initial.label}` : t("fleet.add_model")} onClose={onClose} footer={<button className="primary" onClick={async () => {
      try { if (v.id) await api.put(`/api/fleet/models/${v.id}`, v); else await api.post("/api/fleet/models", v); onSaved(); onClose(); } catch (e) { setErr(e); }
    }}>{t("common.save")}</button>}>
      <div className="form">
        <Field label={t("fleet.manufacturer")}><input value={v.manufacturer || ""} onChange={(e) => setV({ ...v, manufacturer: e.target.value })} /></Field>
        <Field label={t("fleet.model")}><input value={v.model || ""} onChange={(e) => setV({ ...v, model: e.target.value })} /></Field>
        <Field label={<span>{t("fleet.short_name")} <span className="hint" title={t("fleet.short_name_hint")}>?</span></span>}>
          <input value={v.short_name || ""} onChange={(e) => setV({ ...v, short_name: e.target.value })} /></Field>
        <Field label={t("fleet.type")}><select value={v.type} disabled={!!v.machines} onChange={(e) => setV({ ...v, type: e.target.value, params: { ...(meta.types[e.target.value]?.defaults || {}) } })}>
          {Object.keys(meta.types).map((k) => <option key={k} value={k}>{t(`fleet.types.${k}`)}</option>)}</select></Field>
        <Field label={t("fleet.verify")}><input type="checkbox" checked={!!v.verify} onChange={(e) => setV({ ...v, verify: e.target.checked })} /></Field>
        <Field label={t("common.active")}><input type="checkbox" checked={!!v.active} onChange={(e) => setV({ ...v, active: e.target.checked })} /></Field>
      </div>
      <h3>{t("fleet.params")}</h3>
      <ParamsForm type={v.type} meta={meta} value={v.params} onChange={(params) => setV({ ...v, params })} />
      <Field label={t("fleet.note")}><textarea rows={2} value={v.note || ""} onChange={(e) => setV({ ...v, note: e.target.value })} /></Field>
      <ErrorBox error={err} />
    </Modal>
  );
}

/** Короткая сводка по небуровым машинам: «14 т · 6,4 м³». */
function mainParams(m: any, t: (k: string) => string) {
  const p = m.params || {};
  const parts: string[] = [];
  if (p.payload_t != null) parts.push(`${fmtNum(p.payload_t)} ${t("units.t")}`);
  if (p.bucket_m3 != null) parts.push(`${fmtNum(p.bucket_m3)} ${t("units.m3")}`);
  if (p.charge_kg_min != null) parts.push(`${fmtNum(p.charge_kg_min)} ${t("units.kg_min")}`);
  if (p.bolts_per_h != null) parts.push(`${fmtNum(p.bolts_per_h)} ${t("units.pcs_h")}`);
  return parts.join(" · ") || "—";
}

/** Типы машин × виды работ: какая машина на какую работу назначается. */
function TypeWorks({ meta }: { meta: Meta }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const { data, setData } = useApi<Record<string, string[]>>("/api/fleet/type-works");
  const { data: targets } = useApi<any>("/api/staff/permit-targets");
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const works = (targets?.works || []).filter((w: any) => w.assignable);
  if (!data) return null;
  return (
    <Card actions={can("fleet.edit") && <button className="primary" onClick={async () => {
      try { setData(await api.put("/api/fleet/type-works", data)); setSaved(true); } catch (e) { setErr(e); }
    }}>{t("common.save")}</button>}>
      <p className="small muted">{t("fleet.type_works_hint")}</p>
      <div className="tbl-wrap"><table className="t" data-testid="type-works">
        <thead><tr><th>{t("fleet.type")}</th><th>{t("fleet.faces_kind")}</th>{works.map((w: any) => <th key={w.target}>{w.label}</th>)}</tr></thead>
        <tbody>{Object.keys(meta.types).map((tp) => <tr key={tp}>
          <td>{t(`fleet.types.${tp}`)}</td>
          <td>{(meta.types[tp] as any).faces ? t(`dispatch.face_kind.${(meta.types[tp] as any).faces}`) : "—"}</td>
          {works.map((w: any) => <td key={w.target} className="center"><input type="checkbox" disabled={!can("fleet.edit")} checked={(data[tp] || []).includes(w.target)}
            onChange={(e) => { setSaved(false); setData({ ...data, [tp]: e.target.checked ? [...(data[tp] || []), w.target] : (data[tp] || []).filter((x) => x !== w.target) }); }} /></td>)}
        </tr>)}</tbody>
      </table></div>
      {saved && <span className="badge ok">{t("common.saved")}</span>}
      <ErrorBox error={err} />
    </Card>
  );
}

export default function Fleet() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [tab, setTab] = useState("machines");
  const { data, reload } = useApi<any[]>("/api/fleet", 30000);
  const { data: models, reload: reloadModels } = useApi<any[]>("/api/fleet/models");
  const { data: meta } = useApi<Meta>("/api/fleet/meta");
  const [modal, setModal] = useState<any>(null);
  const [modelModal, setModelModal] = useState<any>(null);
  const edit = can("fleet.edit");
  const p = (m: any, k: string) => (DRILLS.includes(m.type) && m.params?.[k] != null ? fmtNum(m.params[k]) : "—");
  const changed = (m: any, ...keys: string[]) => keys.some((k) => m.overrides?.includes(k)) ? " *" : "";
  return (
    <Page title={t("menu.fleet")} actions={edit && tab !== "types" && (tab === "machines"
      ? <button className="primary" onClick={() => setModal({ type: "dev_drill", status: "working", params: {}, model_id: null })}>+ {t("fleet.add")}</button>
      : <button className="primary" onClick={() => setModelModal({ type: "dev_drill", params: { ...(meta?.types.dev_drill.defaults || {}) } })}>+ {t("fleet.add_model")}</button>)}>
      <Tabs value={tab} onChange={setTab} tabs={[["machines", t("fleet.tab_machines")], ["models", t("fleet.tab_models")], ["types", t("fleet.tab_types")]]} />
      {tab === "types" && meta && <TypeWorks meta={meta} />}
      {tab === "machines" && <Card>
        <Table rows={data} onRow={edit && meta && models ? setModal : undefined} cols={[
          { key: "label", title: t("fleet.name"), render: (m) => <b>{m.label}</b> },
          { key: "number", title: t("fleet.number") },
          { key: "model_label", title: t("fleet.model"), render: (m) => m.custom ? <span>{m.model || "—"} <span className="badge warn">{t("fleet.custom_short")}</span></span> : `${m.manufacturer} ${m.model_label}` },
          { key: "type", title: t("fleet.type"), render: (m) => t(`fleet.types.${m.type}`) },
          { key: "booms", title: <span title={t("fleet.hint.booms")}>{t("fleet.col.booms")}</span>, num: true, render: (m) => p(m, "booms") + changed(m, "booms") },
          { key: "dia", title: <span title={t("fleet.hint.dia_min")}>{t("fleet.col.dia")}</span>, render: (m) => DRILLS.includes(m.type) ? `${p(m, "dia_min")}–${p(m, "dia_max")}${changed(m, "dia_min", "dia_max")}` : "—" },
          { key: "len", title: <span title={t("fleet.hint.max_length")}>{t("fleet.col.length")}</span>, num: true, render: (m) => p(m, "max_length") + changed(m, "max_length") },
          { key: "rate", title: <span title={t("fleet.hint.drill_rate_mph")}>{t("fleet.col.rate")}</span>, num: true, render: (m) => p(m, "drill_rate_mph") + changed(m, "drill_rate_mph") },
          { key: "main", title: t("fleet.col.main"), render: (m) => DRILLS.includes(m.type) ? "—" : mainParams(m, t) },
          { key: "status", title: t("common.status"), render: (m) => can("fleet.edit", "dispatch.edit") ? <select value={m.status} onClick={(e) => e.stopPropagation()} onChange={async (e) => { await api.put(`/api/fleet/${m.id}`, { status: e.target.value }); reload(); }}>
            {STATUSES.map((s) => <option key={s} value={s}>{t(`fleet.status.${s}`)}</option>)}</select> : <Badge value={m.status} group="fleet.status" /> },
          { key: "engine_hours", title: t("fleet.engine_hours"), num: true }, { key: "working_name", title: t("fleet.location") },
        ]} />
        <p className="small muted">* {t("fleet.changed_note")}</p>
      </Card>}
      {tab === "models" && <Card>
        <Table rows={models} onRow={edit && meta ? setModelModal : undefined} cols={[
          { key: "manufacturer", title: t("fleet.manufacturer") },
          { key: "label", title: t("fleet.model"), render: (m) => <span><b>{m.label}</b>{!m.active && <span className="muted small"> · {t("common.inactive")}</span>}</span> },
          { key: "type", title: t("fleet.type"), render: (m) => t(`fleet.types.${m.type}`) },
          { key: "dia", title: t("fleet.col.dia"), render: (m) => DRILLS.includes(m.type) ? `${fmtNum(m.params?.dia_min)}–${fmtNum(m.params?.dia_max)}` : "—" },
          { key: "len", title: t("fleet.col.length"), num: true, render: (m) => DRILLS.includes(m.type) ? fmtNum(m.params?.max_length) : "—" },
          { key: "main", title: t("fleet.col.main"), render: (m) => DRILLS.includes(m.type) ? `${fmtNum(m.params?.booms, 0)} × ${fmtNum(m.params?.drill_rate_mph)} ${t("units.m_h")}` : mainParams(m, t) },
          { key: "verify", title: t("fleet.verify"), render: (m) => m.verify ? <span className="badge warn" title={t("fleet.verify_note")}>{t("fleet.verify_short")}</span> : <Badge value="ok" /> },
          { key: "machines", title: t("fleet.machines_count"), num: true },
        ]} />
      </Card>}
      {modal && meta && models && <MachineModal initial={modal} meta={meta} models={models} onClose={() => setModal(null)} onSaved={() => { reload(); reloadModels(); }} />}
      {modelModal && meta && <ModelModal initial={modelModal} meta={meta} onClose={() => setModelModal(null)} onSaved={() => { reloadModels(); reload(); }} />}
    </Page>
  );
}
