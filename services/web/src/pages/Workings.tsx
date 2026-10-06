import { useState } from "react";
import { useTranslation } from "react-i18next";
import Scene3D from "../components/Scene3D";
import { Action, Badge, Card, ErrorBox, Field, Modal, Num, Page, Table, Tabs } from "../components/ui";
import { api, qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { fmtNum } from "../lib/i18n";

function LevelWizard({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const { data: mine } = useApi<any>("/api/mine");
  const { data: ws } = useApi<any[]>("/api/workings?type=ramp");
  const [p, setP] = useState<any>({ level: -325, attach: {}, access: { gradient: 0 }, fwd: { directions: ["N", "S"], length_n: 180, length_s: 180, offset: 20 },
    xc: { enabled: true, spacing: 20, length: "to_hw", angle: 90 }, extras: { sump: true, niche: false, raise: false } });
  const [pv, setPv] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const set = (path: string, v: any) => {
    const [a, b] = path.split(".");
    setP(b ? { ...p, [a]: { ...p[a], [b]: v } } : { ...p, [a]: v });
  };
  return (
    <Modal wide title={t("workings.wizard_level")} onClose={onClose} footer={<>
      <Action onClick={async () => { setErr(null); try { setPv(await api.post("/api/workings/wizard/level", { ...p, preview: true })); } catch (e) { setErr(e); } }}>{t("workings.preview")}</Action>
      <Action className="primary" disabled={!pv} onClick={async () => { try { await api.post("/api/workings/wizard/level", { ...p, preview: false, force: pv?.exists }); onDone(); } catch (e) { setErr(e); } }}>{t("workings.create")}</Action>
    </>}>
      <h3>1. {t("workings.level")}</h3>
      <div className="form">
        <Field label={t("workings.level")}><Num value={p.level} onChange={(v) => set("level", v)} /></Field>
        <Field label={t("workings.attach_to")}><select value={p.attach.working_id || ""} onChange={(e) => set("attach", { ...p.attach, working_id: Number(e.target.value) || undefined })}>
          <option value="">{t("workings.attach_auto")}</option>{(ws || []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></Field>
        <Field label={t("workings.attach_chainage")}><Num value={p.attach.chainage} onChange={(v) => set("attach", { ...p.attach, chainage: v })} placeholder={t("workings.auto")} /></Field>
      </div>
      <h3>2. {t("workings.types.access")}</h3>
      <div className="form">
        <Field label={t("workings.azimuth")}><Num value={p.access.azimuth} onChange={(v) => set("access.azimuth", v)} placeholder={t("workings.auto")} /></Field>
        <Field label={t("workings.length")}><Num value={p.access.length} onChange={(v) => set("access.length", v)} placeholder={t("workings.auto")} /></Field>
        <Field label={t("workings.gradient")}><Num value={p.access.gradient} onChange={(v) => set("access.gradient", v)} /></Field>
      </div>
      <h3>3. {t("workings.types.fwd")}</h3>
      <div className="form">
        <label className="small"><input type="checkbox" checked={p.fwd.directions.includes("N")} onChange={(e) => set("fwd.directions", e.target.checked ? [...p.fwd.directions, "N"] : p.fwd.directions.filter((d: string) => d !== "N"))} />{t("workings.dir.N")}</label>
        <label className="small"><input type="checkbox" checked={p.fwd.directions.includes("S")} onChange={(e) => set("fwd.directions", e.target.checked ? [...p.fwd.directions, "S"] : p.fwd.directions.filter((d: string) => d !== "S"))} />{t("workings.dir.S")}</label>
        <Field label={`${t("workings.length")} (${t("workings.dir.N")})`}><Num value={p.fwd.length_n} onChange={(v) => set("fwd.length_n", v)} /></Field>
        <Field label={`${t("workings.length")} (${t("workings.dir.S")})`}><Num value={p.fwd.length_s} onChange={(v) => set("fwd.length_s", v)} /></Field>
        <Field label={t("workings.offset_ore")}><Num value={p.fwd.offset} onChange={(v) => set("fwd.offset", v)} /></Field>
      </div>
      <h3>4. {t("workings.types.xc")}</h3>
      <div className="form">
        <Field label={t("workings.spacing")}><Num value={p.xc.spacing} onChange={(v) => set("xc.spacing", v)} /></Field>
        <Field label={t("workings.xc_length")}><select value={p.xc.length === "to_hw" ? "to_hw" : "fixed"} onChange={(e) => set("xc.length", e.target.value === "to_hw" ? "to_hw" : 30)}>
          <option value="to_hw">{t("workings.to_hw")}</option><option value="fixed">{t("workings.fixed")}</option></select></Field>
        {p.xc.length !== "to_hw" && <Field label={t("workings.length")}><Num value={p.xc.length} onChange={(v) => set("xc.length", v)} /></Field>}
        <Field label={t("workings.angle")}><Num value={p.xc.angle} onChange={(v) => set("xc.angle", v)} /></Field>
      </div>
      <h3>5. {t("workings.extras")}</h3>
      <div className="row">{["sump", "niche", "raise"].map((k) => <label key={k} className="small"><input type="checkbox" checked={p.extras[k]} onChange={(e) => set(`extras.${k}`, e.target.checked)} />{t(`workings.types.${k}`)}</label>)}</div>
      <div className="small muted">{t("workings.sections_from_mine")}: {mine && Object.entries(mine.config.sections || {}).map(([k, s]: any) => `${t(`workings.types.${k}`)} ${s.width}×${s.height}`).join(" · ")}</div>
      <ErrorBox error={err} />
      {pv && <div style={{ marginTop: 12 }}>
        {pv.exists && <div className="notice">{t("workings.level_exists")}</div>}
        <div className="grid g2">
          <Table rows={pv.items} cols={[{ key: "name", title: t("common.name") }, { key: "type", title: t("workings.type"), render: (w) => t(`workings.types.${w.type}`) }, { key: "length", title: t("workings.length"), num: true }, { key: "azimuth", title: t("workings.azimuth"), num: true }]} />
          <Scene3D height={360} workings={pv.items.map((w: any) => ({ ...w, status: "planned", width: w.section.width }))} />
        </div>
      </div>}
    </Modal>
  );
}

function SublevelWizard({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const [p, setP] = useState<any>({ level_from: -325, level_to: -375, fwd: { length_n: 180, length_s: 180 }, xc: { spacing: 20 } });
  const [pv, setPv] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  return (
    <Modal title={t("workings.wizard_sublevels")} onClose={onClose} footer={<>
      <Action onClick={async () => { try { setPv(await api.post("/api/workings/wizard/sublevels", { ...p, preview: true })); } catch (e) { setErr(e); } }}>{t("workings.preview")}</Action>
      <Action className="primary" disabled={!pv} onClick={async () => { try { await api.post("/api/workings/wizard/sublevels", { ...p, preview: false }); onDone(); } catch (e) { setErr(e); } }}>{t("workings.create")}</Action>
    </>}>
      <div className="form">
        <Field label={t("workings.level_from")}><Num value={p.level_from} onChange={(v) => setP({ ...p, level_from: v })} /></Field>
        <Field label={t("workings.level_to")}><Num value={p.level_to} onChange={(v) => setP({ ...p, level_to: v })} /></Field>
        <Field label={t("workings.sublevel_height")}><Num value={p.height} onChange={(v) => setP({ ...p, height: v })} placeholder={t("workings.from_mine")} /></Field>
        <Field label={t("workings.spacing")}><Num value={p.xc.spacing} onChange={(v) => setP({ ...p, xc: { spacing: v } })} /></Field>
      </div>
      <ErrorBox error={err} />
      {pv && <div className="success">{t("workings.sublevels_preview", { levels: pv.levels.join(", "), n: pv.count })}</div>}
    </Modal>
  );
}

function ManualWorking({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const [p, setP] = useState<any>({ name: "", type: "other", mode: "azimuth", start: [150, 200, -200], azimuth: 90, length: 30, gradient: 0, axisText: "",
    section: { shape: "arch", width: 4.5, height: 4.5, arch_height: 1.1 } });
  const [err, setErr] = useState<unknown>(null);
  return (
    <Modal title={t("workings.manual")} onClose={onClose} footer={<Action className="primary" onClick={async () => {
      try {
        const body: any = { name: p.name, type: p.type, section: p.section };
        if (p.mode === "points") body.axis = p.axisText.trim().split("\n").map((l: string) => l.split(/[ ,;\t]+/).map(Number));
        else Object.assign(body, { start: p.start, azimuth: p.azimuth, length: p.length, gradient: p.gradient });
        await api.post("/api/workings", body); onDone();
      } catch (e) { setErr(e); }
    }}>{t("common.create")}</Action>}>
      <div className="form">
        <Field label={t("common.name")}><input value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} /></Field>
        <Field label={t("workings.type")}><select value={p.type} onChange={(e) => setP({ ...p, type: e.target.value })}>{["ramp", "access", "fwd", "xc", "raise", "sump", "niche", "other"].map((x) => <option key={x} value={x}>{t(`workings.types.${x}`)}</option>)}</select></Field>
        <Field label={t("workings.input_mode")}><select value={p.mode} onChange={(e) => setP({ ...p, mode: e.target.value })}><option value="azimuth">{t("workings.by_azimuth")}</option><option value="points">{t("workings.by_points")}</option></select></Field>
        <Field label={t("dev_passport.width")}><Num value={p.section.width} onChange={(v) => setP({ ...p, section: { ...p.section, width: v } })} /></Field>
        <Field label={t("dev_passport.height")}><Num value={p.section.height} onChange={(v) => setP({ ...p, section: { ...p.section, height: v } })} /></Field>
      </div>
      {p.mode === "azimuth" ? <div className="form" style={{ marginTop: 8 }}>
        {["X", "Y", "Z"].map((c, i) => <Field key={c} label={`${t("workings.start")} ${c}`}><Num value={p.start[i]} onChange={(v) => { const s = [...p.start]; s[i] = v; setP({ ...p, start: s }); }} /></Field>)}
        <Field label={t("workings.azimuth")}><Num value={p.azimuth} onChange={(v) => setP({ ...p, azimuth: v })} /></Field>
        <Field label={t("workings.length")}><Num value={p.length} onChange={(v) => setP({ ...p, length: v })} /></Field>
        <Field label={t("workings.gradient")}><Num value={p.gradient} onChange={(v) => setP({ ...p, gradient: v })} /></Field>
      </div> : <Field label={t("workings.points_hint")}><textarea value={p.axisText} onChange={(e) => setP({ ...p, axisText: e.target.value })} placeholder="150 200 -200&#10;180 200 -200" /></Field>}
      <ErrorBox error={err} />
    </Modal>
  );
}

function DesignerReplace({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const [job, setJob] = useState<any>(null);
  const [cmp, setCmp] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [res, setRes] = useState<any>(null);
  return (
    <Modal wide title={t("workings.designer_replace")} onClose={onClose}>
      <div className="row">
        <label className="btn">{t("workings.upload_plan")}<input type="file" hidden accept=".dxf,.dwg,.str,.csv" onChange={async (e) => {
          const f = e.target.files?.[0]; if (!f) return;
          const fd = new FormData(); fd.append("file", f); fd.append("kind", "workings");
          try { const j = await api.upload("/api/mine/import/upload", fd); setJob(j); setCmp(await api.post("/api/workings/designer/compare", { job_id: j.job_id })); } catch (x) { setErr(x); }
        }} /></label>
        {job && <span className="muted">{job.fmt} · {(job.layers || []).join(", ")}</span>}
      </div>
      <ErrorBox error={err} />
      {cmp && <>
        <div className="row" style={{ margin: "10px 0" }}>{Object.entries(cmp.counts).map(([k, v]) => <span key={k} className={`badge ${k === "match" ? "ok" : k === "missing" ? "err" : "warn"}`}>{t(`workings.cmp.${k}`)}: {String(v)}</span>)}</div>
        <Table rows={cmp.items} cols={[
          { key: "status", title: t("common.status"), render: (r) => <span className={`badge ${r.status === "match" ? "ok" : r.status === "missing" ? "err" : "warn"}`}>{t(`workings.cmp.${r.status}`)}</span> },
          { key: "plan", title: t("workings.plan_name"), render: (r) => r.plan?.name || "—" },
          { key: "working_name", title: t("workings.system_name"), render: (r) => r.working_name || "—" },
          { key: "shift_m", title: t("workings.shift_m"), num: true, render: (r) => r.shift_m !== null ? `${fmtNum(r.shift_m, 2)} (max ${fmtNum(r.shift_max_m, 2)})` : "—" },
          { key: "matched_by", title: t("workings.matched_by"), render: (r) => r.matched_by ? t(`workings.match_by.${r.matched_by}`) : "" },
        ]} />
        <div className="row" style={{ marginTop: 10 }}>
          <Action className="primary" onClick={async () => { try { setRes(await api.post("/api/workings/designer/replace", { job_id: job.job_id })); onDone(); } catch (e) { setErr(e); } }}>{t("workings.confirm_replace")}</Action>
          <span className="muted small">{t("workings.replace_note")}</span>
        </div>
        {res && <div className="success">{String(t("workings.replaced", res))}</div>}
      </>}
    </Modal>
  );
}

export default function Workings() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [f, setF] = useState<any>({});
  const { data, reload } = useApi<any[]>("/api/workings" + qs(f), 0, [f.level, f.type, f.status]);
  const { data: scene } = useApi<any>("/api/mine/scene");
  const [modal, setModal] = useState("");
  const [tab, setTab] = useState("list");
  const [sel, setSel] = useState<any>(null);
  const { data: detail } = useApi<any>(sel ? `/api/workings/${sel.id}` : null, 0, [sel?.id]);
  const edit = can("workings.edit");
  const done = () => { setModal(""); reload(); };
  return (
    <Page title={t("menu.workings")} actions={edit && <>
      <button className="primary" onClick={() => setModal("level")}>{t("workings.wizard_level")}</button>
      <button onClick={() => setModal("sub")}>{t("workings.wizard_sublevels")}</button>
      <button onClick={() => setModal("manual")}>{t("workings.manual")}</button>
      <button onClick={() => setModal("designer")}>{t("workings.designer_replace")}</button>
    </>}>
      <div className="row" style={{ marginBottom: 10 }}>
        <select value={f.level || ""} onChange={(e) => setF({ ...f, level: e.target.value })}><option value="">{t("common.all_levels")}</option>{(scene?.levels || []).map((l: number) => <option key={l} value={l}>{l}</option>)}</select>
        <select value={f.type || ""} onChange={(e) => setF({ ...f, type: e.target.value })}><option value="">{t("common.all")}</option>{["ramp", "access", "fwd", "xc", "raise", "sump", "niche", "other"].map((x) => <option key={x} value={x}>{t(`workings.types.${x}`)}</option>)}</select>
        <select value={f.status || ""} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">{t("common.all")}</option>{["planned", "driving", "done", "closed"].map((x) => <option key={x} value={x}>{t(`workings.status.${x}`)}</option>)}</select>
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[["list", t("workings.list")], ["plan", t("workings.plan_view")]]} />
      {tab === "list" && <Card>
        <Table rows={data} onRow={setSel} cols={[
          { key: "name", title: t("common.name") }, { key: "type", title: t("workings.type"), render: (w) => t(`workings.types.${w.type}`) },
          { key: "level", title: t("common.level_short"), num: true },
          { key: "status", title: t("common.status"), render: (w) => <Badge value={w.status} group="workings.status" /> },
          { key: "source", title: t("workings.source"), render: (w) => t(`workings.sources.${w.source}`) },
          { key: "length", title: t("workings.length"), num: true }, { key: "azimuth", title: t("workings.azimuth"), num: true },
          { key: "area", title: t("dev_passport.area"), num: true, render: (w) => fmtNum(w.section?.area, 1) },
          { key: "volume", title: t("workings.volume"), num: true, render: (w) => fmtNum(w.volume, 0) },
          { key: "act", title: "", render: (w) => edit ? <select value={w.status} onClick={(e) => e.stopPropagation()} onChange={async (e) => { await api.put(`/api/workings/${w.id}`, { status: e.target.value }); reload(); }}>
            {["planned", "driving", "done", "closed"].map((x) => <option key={x} value={x}>{t(`workings.status.${x}`)}</option>)}</select> : null },
        ]} />
      </Card>}
      {tab === "plan" && <Card><Scene3D height={560} workings={(scene?.workings || []).filter((w: any) => !f.level || w.level === Number(f.level) || w.type === "ramp")} stopes={[]} onPick={(p) => p.kind === "working" && setSel(p.data)} /></Card>}
      {detail && <Card title={detail.name} actions={<button className="small" onClick={() => setSel(null)}>✕</button>}>
        <div className="kv">
          <div>{t("workings.length")}</div><div>{fmtNum(detail.length)} {t("units.m")} ({detail.chainage_label})</div>
          <div>{t("dev_passport.section")}</div><div>{t(`dev_passport.shapes.${detail.section.shape}`)} {detail.section.width}×{detail.section.height}, {fmtNum(detail.section.area, 2)} {t("units.m2")}</div>
          <div>{t("workings.faces")}</div><div>{detail.faces.map((x: any) => `${x.name} (${t(`workflow.status.${x.status}`)})`).join(", ") || "—"}</div>
          <div>{t("menu.passports")}</div><div>{detail.passports.map((x: any) => x.number).join(", ") || "—"}</div>
        </div>
        <h3>{t("workings.geology_profile")}</h3>
        <div className="row">{detail.geology_profile.map((g: any) => <span key={g.ch} className={`badge ${g.water !== "dry" && g.water !== "damp" ? "info" : g.fracture_cat >= 4 ? "warn" : ""}`} title={`${g.rock_name} · ${t(`geology.targets.${g.priority}`)}`}>ПК {Math.floor(g.ch / 100)}+{String(Math.round(g.ch % 100)).padStart(2, "0")}: f{g.f} {g.water !== "dry" ? "💧" : ""}{g.fracture_cat >= 4 ? "⚡" : ""}{g.cleavage ? "∥" : ""}</span>)}</div>
      </Card>}
      {modal === "level" && <LevelWizard onClose={() => setModal("")} onDone={done} />}
      {modal === "sub" && <SublevelWizard onClose={() => setModal("")} onDone={done} />}
      {modal === "manual" && <ManualWorking onClose={() => setModal("")} onDone={done} />}
      {modal === "designer" && <DesignerReplace onClose={() => setModal("")} onDone={reload} />}
    </Page>
  );
}
