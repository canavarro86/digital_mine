import { useState, Fragment } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import FaceSvg from "../components/FaceSvg";
import { Action, Badge, Card, ErrorBox, Field, Modal, Num, Page, Table } from "../components/ui";
import { api, download } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { fmtNum } from "../lib/i18n";

const WATER = ["dry", "damp", "dripping", "flowing", "inflow"];

function NewTypical({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const { data: expl } = useApi<any[]>("/api/explosives");
  const [f, setF] = useState<any>({ number: "", name: "", working_type: "fwd", f_min: 8, f_max: 14, water: ["dry", "damp"], mode: "calc",
    input: { section: { shape: "arch", width: 5, height: 5, arch_height: 1.25 }, hole_depth: 3.8, hole_diameter: 45, rock_override: {}, rock: { f: 12, fracture_cat: 3, density: 2.75, water: "dry" } } });
  const [err, setErr] = useState<unknown>(null);
  return (
    <Modal title={t("typical.new")} onClose={onClose} footer={<button className="primary" onClick={async () => {
      try {
        const body = f.mode === "calc" ? f : { ...f, input: undefined, section: f.input.section, indicators: f.indicators || {} };
        const r = await api.post("/api/passports/typical", body);
        nav(`/typical/${r.id}`);
      } catch (e) { setErr(e); }
    }}>{t("common.create")}</button>}>
      <div className="form">
        <Field label="№"><input value={f.number} onChange={(e) => setF({ ...f, number: e.target.value })} /></Field>
        <Field label={t("common.name")}><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label={t("workings.type")}><select value={f.working_type} onChange={(e) => setF({ ...f, working_type: e.target.value })}>{["ramp", "access", "fwd", "xc", "raise", "other"].map((x) => <option key={x} value={x}>{t(`workings.types.${x}`)}</option>)}</select></Field>
        <Field label="f min"><Num value={f.f_min} onChange={(v) => setF({ ...f, f_min: v })} /></Field>
        <Field label="f max"><Num value={f.f_max} onChange={(v) => setF({ ...f, f_max: v })} /></Field>
        <Field label={t("typical.mode")}><select value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}><option value="calc">{t("typical.mode_calc")}</option><option value="manual">{t("typical.mode_manual")}</option></select></Field>
        <Field label={t("dev_passport.width")}><Num value={f.input.section.width} onChange={(v) => setF({ ...f, input: { ...f.input, section: { ...f.input.section, width: v } } })} /></Field>
        <Field label={t("dev_passport.height")}><Num value={f.input.section.height} onChange={(v) => setF({ ...f, input: { ...f.input, section: { ...f.input.section, height: v } } })} /></Field>
        <Field label={t("dev_passport.depth")}><Num value={f.input.hole_depth} onChange={(v) => setF({ ...f, input: { ...f.input, hole_depth: v } })} /></Field>
        <Field label={t("explosives.explosive")}><select value={f.input.explosive_id || ""} onChange={(e) => setF({ ...f, input: { ...f.input, explosive_id: Number(e.target.value) } })}><option value="">—</option>{(expl || []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
        <Field label={t("geology.f")}><Num value={f.input.rock.f} onChange={(v) => setF({ ...f, input: { ...f.input, rock: { ...f.input.rock, f: v } } })} /></Field>
      </div>
      <div className="row" style={{ marginTop: 8 }}>{WATER.map((w) => <label key={w} className="small"><input type="checkbox" checked={f.water.includes(w)} onChange={(e) => setF({ ...f, water: e.target.checked ? [...f.water, w] : f.water.filter((x: string) => x !== w) })} />{t(`geology.water_levels.${w}`)}</label>)}</div>
      <ErrorBox error={err} />
    </Modal>
  );
}

export function TypicalList() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const { can } = useAuth();
  const { data } = useApi<any[]>("/api/passports/typical");
  const [modal, setModal] = useState(false);
  return (
    <Page title={t("menu.typical")} actions={can("passports.edit") && <button className="primary" onClick={() => setModal(true)}>+ {t("typical.new")}</button>}>
      <Card>
        <Table rows={data} onRow={(p) => nav(`/typical/${p.id}`)} cols={[
          { key: "number", title: "№" }, { key: "name", title: t("common.name") },
          { key: "working_type", title: t("workings.type"), render: (p) => t(`workings.types.${p.working_type}`) },
          { key: "section", title: t("dev_passport.section"), render: (p) => p.section?.width ? `${p.section.width}×${p.section.height} (${fmtNum(p.section.area, 1)} ${t("units.m2")})` : "—" },
          { key: "f", title: "f", render: (p) => `${p.f_min}–${p.f_max}` },
          { key: "water", title: t("geology.water"), render: (p) => (p.water || []).map((w: string) => t(`geology.water_levels.${w}`)).join(", ") },
          { key: "version", title: t("common.version"), num: true },
          { key: "status", title: t("common.status"), render: (p) => <Badge value={p.status} group="passport_status" /> },
          { key: "approved_by", title: t("typical.approved_by"), render: (p) => p.approved_by ? `${p.approved_by} ${p.approved_at?.slice(0, 10) || ""}` : "" },
        ]} />
      </Card>
      {modal && <NewTypical onClose={() => setModal(false)} />}
    </Page>
  );
}

export function TypicalDetail() {
  const { id } = useParams();
  const { t } = useTranslation();
  const { can } = useAuth();
  const { data: p, reload, error } = useApi<any>(`/api/passports/typical/${id}`, 0, [id]);
  const { data: ws } = useApi<any[]>("/api/workings");
  const [assign, setAssign] = useState<any>(null);
  const [inp, setInp] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  if (!p) return <ErrorBox error={error} />;
  const edit = can("passports.edit");
  const a = assign || { working_types: p.assigned?.working_types || [], working_ids: p.assigned?.working_ids || [], intervals: p.assigned?.intervals || [] };
  return (
    <Page title={<>{p.number} {p.name} <Badge value={p.status} group="passport_status" /> <span className="badge">v{p.version}</span></>} actions={<>
      {edit && p.status === "draft" && <Action onClick={async () => { await api.post(`/api/passports/typical/${p.id}/status`, { status: "review" }); reload(); }}>{t("passport_status_action.review")}</Action>}
      {can("passports.approve") && p.status === "review" && <Action className="primary" onClick={async () => { await api.post(`/api/passports/typical/${p.id}/status`, { status: "approved" }); reload(); }}>{t("passport_status_action.approved")}</Action>}
      {edit && p.status === "approved" && <Action onClick={async () => { await api.post(`/api/passports/typical/${p.id}/status`, { status: "archived" }); reload(); }}>{t("passport_status_action.archived")}</Action>}
      {edit && <label className="btn">{t("typical.attach")}<input type="file" hidden accept=".pdf,.dxf,.dwg" onChange={async (e) => {
        const f = e.target.files?.[0]; if (!f) return; const fd = new FormData(); fd.append("file", f);
        await api.upload(`/api/passports/typical/${p.id}/attachment`, fd); reload();
      }} /></label>}
    </>}>
      <ErrorBox error={err} />
      <div className="grid g2">
        <Card title={t("dev_passport.face_view")}>{p.design?.holes ? <FaceSvg result={p.design} size={460} /> : <span className="muted">{t("typical.no_drawing")}</span>}</Card>
        <div>
          <Card title={t("dev_passport.indicators")}>
            <div className="kv">{Object.entries(p.indicators || {}).filter(([, v]) => typeof v !== "object").map(([k, v]) => <Fragment key={k}><div>{t(`dev_passport.ind.${k}`, { defaultValue: k })}</div><div>{fmtNum(v, 2)}</div></Fragment>)}</div>
          </Card>
          {edit && p.input?.section && <Card title={t("typical.edit_params")}>
            <div className="form">
              <Field label={t("dev_passport.depth")}><Num value={(inp || p.input).hole_depth} onChange={(v) => setInp({ ...(inp || {}), hole_depth: v })} /></Field>
              <Field label={t("dev_passport.diameter_work")}><Num value={(inp || p.input).hole_diameter} onChange={(v) => setInp({ ...(inp || {}), hole_diameter: v })} /></Field>
              <Field label={t("dev_passport.width")}><Num value={(inp?.section || p.input.section).width} onChange={(v) => setInp({ ...(inp || {}), section: { ...p.input.section, ...(inp?.section || {}), width: v } })} /></Field>
              <Field label={t("dev_passport.height")}><Num value={(inp?.section || p.input.section).height} onChange={(v) => setInp({ ...(inp || {}), section: { ...p.input.section, ...(inp?.section || {}), height: v } })} /></Field>
              <Action className="primary" disabled={!inp} onClick={async () => { try { await api.put(`/api/passports/typical/${p.id}`, { input: inp, note: "UI" }); setInp(null); reload(); } catch (e) { setErr(e); } }}>{t("typical.new_version")}</Action>
            </div>
          </Card>}
          <Card title={t("typical.assignment")}>
            <div className="row">{["ramp", "access", "fwd", "xc", "raise"].map((wt) => <label key={wt} className="small"><input type="checkbox" disabled={!edit} checked={a.working_types.includes(wt)} onChange={(e) => setAssign({ ...a, working_types: e.target.checked ? [...a.working_types, wt] : a.working_types.filter((x: string) => x !== wt) })} />{t(`workings.types.${wt}`)}</label>)}</div>
            <Field label={t("typical.working_ids")}>
              <select multiple disabled={!edit} style={{ height: 110 }} value={a.working_ids.map(String)} onChange={(e) => setAssign({ ...a, working_ids: [...e.target.selectedOptions].map((o) => Number(o.value)) })}>
                {(ws || []).filter((w) => w.type !== "ramp").map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            </Field>
            {edit && <Action className="primary" disabled={!assign} onClick={async () => { await api.put(`/api/passports/typical/${p.id}`, { assigned: a }); setAssign(null); reload(); }}>{t("common.save")}</Action>}
          </Card>
          {(p.attachments || []).length > 0 && <Card title={t("typical.attachments")}>{p.attachments.map((x: any, i: number) => <div key={i}><a href="#" onClick={(e) => { e.preventDefault(); download(`/api/passports/typical/${p.id}/attachment/${i}`, x.name); }}>{x.name}</a> <span className="muted small">{x.ts}</span></div>)}</Card>}
        </div>
      </div>
      <Card title={t("typical.versions")}>
        <Table rows={p.versions} cols={[
          { key: "version", title: "v", num: true }, { key: "ts", title: t("common.time"), render: (v) => v.ts?.slice(0, 16).replace("T", " ") },
          { key: "changed_by", title: t("common.user") },
          { key: "changes", title: t("typical.changes"), render: (v) => (v.changes || []).map((c: any) => `${c.field}: ${JSON.stringify(c.was)} → ${JSON.stringify(c.now)}`).join("; ") },
          { key: "note", title: t("common.comment") },
        ]} />
      </Card>
    </Page>
  );
}
