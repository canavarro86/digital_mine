import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Action, Badge, Card, ErrorBox, Field, Modal, Num, Page, Table, Tabs } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { fmtNum } from "../lib/i18n";

const WATER = ["dry", "damp", "dripping", "flowing", "inflow"];

/** Универсальная форма по списку полей. */
function FormModal({ title, fields, initial, onSave, onClose }: {
  title: string; fields: { key: string; label: string; type?: "num" | "text" | "select" | "date" | "check"; options?: [string, string][] }[];
  initial: any; onSave: (v: any) => Promise<unknown>; onClose: () => void;
}) {
  const { t } = useTranslation();
  const [v, setV] = useState<any>(initial);
  const [err, setErr] = useState<unknown>(null);
  return (
    <Modal title={title} onClose={onClose} footer={<button className="primary" onClick={async () => { try { await onSave(v); onClose(); } catch (e) { setErr(e); } }}>{t("common.save")}</button>}>
      <div className="form">{fields.map((f) => <Field key={f.key} label={f.label}>
        {f.type === "num" ? <Num value={v[f.key]} onChange={(x) => setV({ ...v, [f.key]: x })} />
          : f.type === "select" ? <select value={v[f.key] ?? ""} onChange={(e) => setV({ ...v, [f.key]: e.target.value })}>{f.options!.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          : f.type === "check" ? <input type="checkbox" checked={!!v[f.key]} onChange={(e) => setV({ ...v, [f.key]: e.target.checked })} />
          : <input type={f.type === "date" ? "date" : "text"} value={v[f.key] ?? ""} onChange={(e) => setV({ ...v, [f.key]: e.target.value })} />}
      </Field>)}</div>
      <ErrorBox error={err} />
    </Modal>
  );
}

export function Geology() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const { data: rocks, reload: rr } = useApi<any[]>("/api/geology/rocks");
  const { data: asg, reload: ra } = useApi<any[]>("/api/geology/assignments");
  const { data: ws } = useApi<any[]>("/api/workings");
  const { data: meta } = useApi<any>("/api/geology/meta");
  const [tab, setTab] = useState("assign");
  const [modal, setModal] = useState<any>(null);
  const [probe, setProbe] = useState<any>({});
  const [probeRes, setProbeRes] = useState<any>(null);
  const edit = can("geology.edit");
  const rockOpts: [string, string][] = (rocks || []).map((r) => [String(r.id), r.name]);
  const rockFields = [
    { key: "code", label: t("geology.code") }, { key: "name", label: t("common.name") },
    { key: "kind", label: t("geology.kind"), type: "select" as const, options: ["ore", "waste", "contact"].map((k) => [k, t(`geology.kinds.${k}`)] as [string, string]) },
    { key: "f", label: t("geology.f"), type: "num" as const }, { key: "ucs", label: "UCS, " + t("units.mpa"), type: "num" as const },
    { key: "density", label: t("geology.density"), type: "num" as const }, { key: "fracture_cat", label: t("geology.fracture_cat"), type: "num" as const },
    { key: "fracture_spacing", label: t("geology.fracture_spacing"), type: "num" as const }, { key: "rqd", label: "RQD, %", type: "num" as const },
    { key: "rmr", label: "RMR", type: "num" as const }, { key: "q", label: "Q", type: "num" as const },
    { key: "water", label: t("geology.water"), type: "select" as const, options: WATER.map((w) => [w, t(`geology.water_levels.${w}`)] as [string, string]) },
    { key: "inflow_lpm", label: t("geology.inflow"), type: "num" as const },
    ...((meta?.extra_params || []) as any[]).map((p) => ({ key: `extra_${p.key}`, label: `${p.label?.[t("_meta.code", { defaultValue: "ru" })] || p.key}${p.unit ? ", " + p.unit : ""}`, type: "num" as const })),
  ];
  return (
    <Page title={t("menu.geology")} actions={edit && <>
      <button className="primary" onClick={() => setModal({ kind: "assign", v: { target: "interval", overrides: {} } })}>+ {t("geology.assign")}</button>
      <button onClick={() => setModal({ kind: "rock", v: { kind: "waste", f: 10, density: 2.7, fracture_cat: 3, water: "dry" } })}>+ {t("geology.rock")}</button>
    </>}>
      <Tabs value={tab} onChange={setTab} tabs={[["assign", t("geology.assignments")], ["rocks", t("geology.rocks")], ["probe", t("geology.probe")]]} />
      {tab === "assign" && <Card>
        <div className="small muted" style={{ marginBottom: 6 }}>{t("geology.priority_note")}</div>
        <Table rows={asg} cols={[
          { key: "target", title: t("geology.target"), render: (a) => <Badge value={t(`geology.targets.${a.target}`)} /> },
          { key: "name", title: t("common.name") }, { key: "working_name", title: t("workings.working") },
          { key: "interval", title: t("geology.interval"), render: (a) => a.target === "interval" ? `ПК ${a.ch_from} … ${a.ch_to}` : a.target === "zone" ? `${(a.zone.min || []).join(",")} … ${(a.zone.max || []).join(",")}` : "" },
          { key: "rock", title: t("geology.rock"), render: (a) => (rocks || []).find((r) => r.id === a.rock_type_id)?.name || "—" },
          { key: "overrides", title: t("geology.overrides"), render: (a) => Object.entries(a.overrides || {}).map(([k, v]) => k === "water" ? t(`geology.water_levels.${v}`) : k === "faults" ? (v as any[]).map((f) => t(`geology.faults.${f.type}`)).join(", ") : `${k}=${JSON.stringify(v)}`).join("; ") },
          { key: "act", title: "", render: (a) => edit ? <Action className="small" confirm={t("common.confirm_delete")} onClick={async () => { await api.del(`/api/geology/assignments/${a.id}`); ra(); }}>✕</Action> : null },
        ]} />
      </Card>}
      {tab === "rocks" && <Card>
        <Table rows={rocks} onRow={edit ? (r) => setModal({ kind: "rock", v: r }) : undefined} cols={[
          { key: "code", title: t("geology.code") }, { key: "name", title: t("common.name") }, { key: "kind", title: t("geology.kind"), render: (r) => t(`geology.kinds.${r.kind}`) },
          { key: "f", title: "f", num: true }, { key: "ucs", title: "UCS", num: true }, { key: "density", title: t("geology.density"), num: true },
          { key: "fracture_cat", title: t("geology.fracture_cat"), num: true }, { key: "rqd", title: "RQD", num: true }, { key: "rmr", title: "RMR", num: true },
          { key: "water", title: t("geology.water"), render: (r) => t(`geology.water_levels.${r.water}`) },
          { key: "grades", title: t("geology.grades"), render: (r) => Object.entries(r.grades || {}).map(([m, g]: any) => `${m} ${g.value} ${g.unit}`).join(", ") },
        ]} />
      </Card>}
      {tab === "probe" && <Card>
        <div className="form">
          <Field label={t("workings.working")}><select value={probe.working_id || ""} onChange={(e) => setProbe({ ...probe, working_id: e.target.value })}><option value="">—</option>{(ws || []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></Field>
          <Field label={t("geology.chainage")}><Num value={probe.chainage} onChange={(v) => setProbe({ ...probe, chainage: v })} /></Field>
          <Action className="primary" onClick={async () => setProbeRes(await api.get(`/api/geology/at?working_id=${probe.working_id}&chainage=${probe.chainage || 0}`))}>{t("geology.show")}</Action>
        </div>
        {probeRes && <div className="kv" style={{ marginTop: 10 }}>
          <div>{t("geology.rock")}</div><div>{probeRes.rock_name}</div><div>f</div><div>{probeRes.f}</div>
          <div>{t("geology.water")}</div><div>{t(`geology.water_levels.${probeRes.water}`)}</div><div>{t("geology.fracture_cat")}</div><div>{probeRes.fracture_cat}</div>
          <div>{t("geology.priority")}</div><div>{t(`geology.targets.${probeRes.priority}`)}</div>
          <div>{t("geology.sources")}</div><div>{probeRes.source.map((s: any) => `${t(`geology.targets.${s.level}`)}: ${s.name}`).join(" → ")}</div>
        </div>}
      </Card>}
      {modal?.kind === "rock" && <FormModal title={t("geology.rock")} fields={rockFields} initial={modal.v} onClose={() => setModal(null)}
        onSave={async (v) => { if (v.id) await api.put(`/api/geology/rocks/${v.id}`, v); else await api.post("/api/geology/rocks", v); rr(); }} />}
      {modal?.kind === "assign" && <FormModal title={t("geology.assign")} initial={modal.v} onClose={() => setModal(null)}
        fields={[
          { key: "target", label: t("geology.target"), type: "select", options: ["interval", "working", "zone", "mine"].map((k) => [k, t(`geology.targets.${k}`)]) },
          { key: "name", label: t("common.name") },
          { key: "working_id", label: t("workings.working"), type: "select", options: [["", "—"], ...(ws || []).map((w) => [String(w.id), w.name] as [string, string])] },
          { key: "ch_from", label: t("geology.ch_from"), type: "num" }, { key: "ch_to", label: t("geology.ch_to"), type: "num" },
          { key: "zone_min", label: t("geology.zone_min") }, { key: "zone_max", label: t("geology.zone_max") },
          { key: "rock_type_id", label: t("geology.rock"), type: "select", options: [["", "—"], ...rockOpts] },
          { key: "water", label: t("geology.water"), type: "select", options: [["", "—"], ...WATER.map((w) => [w, t(`geology.water_levels.${w}`)] as [string, string])] },
          { key: "fracture_cat", label: t("geology.fracture_cat"), type: "num" },
          { key: "fault", label: t("geology.fault"), type: "select", options: [["", "—"], ...["fault", "cleavage", "crush_zone", "blocky"].map((k) => [k, t(`geology.faults.${k}`)] as [string, string])] },
          { key: "fault_az", label: t("geology.azimuth"), type: "num" }, { key: "fault_dip", label: t("geology.dip"), type: "num" },
        ]}
        onSave={async (v) => {
          const ov: any = {};
          if (v.water) ov.water = v.water;
          if (v.fracture_cat) ov.fracture_cat = v.fracture_cat;
          if (v.fault) ov.faults = [{ type: v.fault, azimuth: v.fault_az, dip: v.fault_dip }];
          const zone = v.zone_min && v.zone_max ? { min: v.zone_min.split(/[ ,;]+/).map(Number), max: v.zone_max.split(/[ ,;]+/).map(Number) } : {};
          await api.post("/api/geology/assignments", { target: v.target, name: v.name, working_id: v.working_id ? Number(v.working_id) : null, ch_from: v.ch_from, ch_to: v.ch_to,
            rock_type_id: v.rock_type_id ? Number(v.rock_type_id) : null, overrides: ov, zone });
          ra();
        }} />}
    </Page>
  );
}

export function Explosives() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const { data: ex, reload } = useApi<any[]>("/api/explosives");
  const { data: init, reload: ri } = useApi<any[]>("/api/initiation");
  const { data: ws } = useApi<any[]>("/api/workings?status=driving");
  const [modal, setModal] = useState<any>(null);
  const [chk, setChk] = useState<any>({ diameter: 45 });
  const [chkRes, setChkRes] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const edit = can("explosives.edit");
  const fields: any[] = [
    { key: "code", label: t("geology.code") }, { key: "name", label: t("common.name") }, { key: "manufacturer", label: t("explosives.manufacturer") },
    { key: "type", label: t("explosives.type"), type: "select", options: ["emulsion", "anfo", "cartridge"].map((k) => [k, t(`explosives.types.${k}`)]) },
    { key: "density_min", label: t("explosives.density_min"), type: "num" }, { key: "density_max", label: t("explosives.density_max"), type: "num" },
    { key: "vod", label: "VOD, " + t("units.mps"), type: "num" }, { key: "rws", label: "RWS, %", type: "num" }, { key: "rbs", label: "RBS, %", type: "num" },
    { key: "heat", label: t("explosives.heat"), type: "num" }, { key: "gas", label: t("explosives.gas"), type: "num" },
    { key: "water_resistance", label: t("explosives.water_resistance"), type: "select", options: ["none", "limited", "full"].map((k) => [k, t(`explosives.wr.${k}`)]) },
    { key: "crit_diameter", label: t("explosives.crit_diameter"), type: "num" }, { key: "min_diameter", label: t("explosives.min_diameter"), type: "num" },
    { key: "cart_diameter", label: t("explosives.cart_diameter"), type: "num" }, { key: "cart_length", label: t("explosives.cart_length"), type: "num" },
    { key: "cart_mass", label: t("explosives.cart_mass"), type: "num" }, { key: "price", label: t("explosives.price"), type: "num" },
  ];
  return (
    <Page title={t("menu.explosives")} actions={edit && <button className="primary" onClick={() => setModal({ kind: "ex", v: { type: "emulsion", water_resistance: "full", density_min: 1.1, density_max: 1.2, rws: 80, rbs: 110, vod: 5000, crit_diameter: 32, min_diameter: 35, price: 1.5 } })}>+ {t("explosives.explosive")}</button>}>
      <Card title={t("explosives.list")}>
        <Table rows={ex} onRow={edit ? (r) => setModal({ kind: "ex", v: r }) : undefined} cols={[
          { key: "name", title: t("common.name") }, { key: "type", title: t("explosives.type"), render: (r) => t(`explosives.types.${r.type}`) },
          { key: "density", title: t("explosives.density"), render: (r) => `${r.density_min}–${r.density_max}` }, { key: "vod", title: "VOD", num: true },
          { key: "rws", title: "RWS", num: true }, { key: "rbs", title: "RBS", num: true },
          { key: "water_resistance", title: t("explosives.water_resistance"), render: (r) => <Badge value={t(`explosives.wr.${r.water_resistance}`)} /> },
          { key: "crit_diameter", title: t("explosives.crit_diameter"), num: true }, { key: "price", title: t("explosives.price"), num: true },
        ]} />
      </Card>
      <Card title={t("explosives.check_title")}>
        <div className="form">
          <Field label={t("explosives.explosive")}><select value={chk.explosive_id || ""} onChange={(e) => setChk({ ...chk, explosive_id: Number(e.target.value) })}><option value="">—</option>{(ex || []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
          <Field label={t("workings.working")}><select value={chk.working_id || ""} onChange={(e) => setChk({ ...chk, working_id: Number(e.target.value) || null })}><option value="">—</option>{(ws || []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></Field>
          <Field label={t("geology.chainage")}><Num value={chk.chainage} onChange={(v) => setChk({ ...chk, chainage: v })} /></Field>
          <Field label={t("geology.water")}><select value={chk.water || ""} onChange={(e) => setChk({ ...chk, water: e.target.value })}><option value="">—</option>{WATER.map((w) => <option key={w} value={w}>{t(`geology.water_levels.${w}`)}</option>)}</select></Field>
          <Field label={t("dev_passport.diameter_mm")}><Num value={chk.diameter} onChange={(v) => setChk({ ...chk, diameter: v })} /></Field>
          <Action className="primary" onClick={async () => { setErr(null); try { setChkRes(await api.post("/api/explosives/check", chk)); } catch (e) { setErr(e); } }}>{t("explosives.check")}</Action>
        </div>
        <ErrorBox error={err} />
        {chkRes && <div style={{ marginTop: 8 }}>
          <div className={chkRes.ok ? "success" : "error"}>{chkRes.ok ? t("explosives.check_ok") : t("explosives.check_forbidden")} · {t("geology.water")}: {t(`geology.water_levels.${chkRes.water}`)} · {fmtNum(chkRes.kg_per_m, 2)} {t("units.kg")}/{t("units.m")}</div>
          {chkRes.issues.map((i: any, k: number) => <div key={k} className={i.level === "error" ? "error" : "notice"}>{String(t(`errors.${i.code}`, i.params))}</div>)}
          {chkRes.alternatives.length > 0 && <div>{t("explosives.alternatives")}: {chkRes.alternatives.map((a: any) => a.name).join(", ")}</div>}
        </div>}
      </Card>
      <Card title={t("explosives.initiation")} actions={edit && <button className="small" onClick={() => setModal({ kind: "init", v: { kind: "edd", props: {} } })}>+</button>}>
        <Table rows={init} onRow={edit ? (r) => setModal({ kind: "init", v: r }) : undefined} cols={[
          { key: "name", title: t("common.name") }, { key: "kind", title: t("explosives.kind"), render: (r) => t(`explosives.kinds.${r.kind}`) },
          { key: "props", title: t("explosives.props"), render: (r) => Object.entries(r.props || {}).map(([k, v]) => `${t(`explosives.p.${k}`, { defaultValue: k })}: ${Array.isArray(v) ? v.join(",") : v}`).join("; ") },
          { key: "price", title: t("explosives.price"), num: true },
        ]} />
      </Card>
      {modal?.kind === "ex" && <FormModal title={t("explosives.explosive")} fields={fields} initial={modal.v} onClose={() => setModal(null)}
        onSave={async (v) => { if (v.id) await api.put(`/api/explosives/${v.id}`, v); else await api.post("/api/explosives", v); reload(); }} />}
      {modal?.kind === "init" && <FormModal title={t("explosives.initiation")} initial={{ ...modal.v, props_json: JSON.stringify(modal.v.props || {}) }} onClose={() => setModal(null)}
        fields={[{ key: "code", label: t("geology.code") }, { key: "name", label: t("common.name") },
          { key: "kind", label: t("explosives.kind"), type: "select", options: ["primer", "nonel", "edd", "detcord"].map((k) => [k, t(`explosives.kinds.${k}`)]) },
          { key: "props_json", label: t("explosives.props") + " (JSON)" }, { key: "price", label: t("explosives.price"), type: "num" }]}
        onSave={async (v) => { const body = { ...v, props: JSON.parse(v.props_json || "{}") }; if (v.id) await api.put(`/api/initiation/${v.id}`, body); else await api.post("/api/initiation", body); ri(); }} />}
    </Page>
  );
}
