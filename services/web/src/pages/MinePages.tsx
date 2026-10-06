import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Scene3D from "../components/Scene3D";
import ShiftsEditor from "../components/ShiftsEditor";
import { Action, Card, ErrorBox, Field, Num, Page, Table } from "../components/ui";
import { api, download } from "../lib/api";
import { useApi } from "../lib/hooks";

const TYPES = ["ramp", "access", "fwd", "xc", "raise", "sump", "niche"];

export function MineSettings() {
  const { t } = useTranslation();
  const { data, reload } = useApi<any>("/api/mine");
  const { data: list, reload: reloadList } = useApi<any>("/api/mine/list");
  const { data: typ } = useApi<any[]>("/api/passports/typical");
  const [cfg, setCfg] = useState<any>(null);
  const [ok, setOk] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const { data: shiftsNow } = useApi<any>("/api/mine/shifts", 0, [data]);
  const [shiftsOk, setShiftsOk] = useState(true);
  useEffect(() => { if (data && shiftsNow) setCfg({ ...JSON.parse(JSON.stringify(data.config)), shifts: { table: shiftsNow.table, blast_windows: shiftsNow.blast_windows, ventilation_min: shiftsNow.ventilation_min, reentry_min: shiftsNow.reentry_min, blast_zone: shiftsNow.blast_zone } }); }, [data, shiftsNow]);
  if (!cfg) return null;
  const set = (k: string, v: any) => setCfg({ ...cfg, [k]: v });
  return (
    <Page title={`${t("menu.mine")}: ${data.name}`} actions={<>
      <Action onClick={() => download("/api/mine/export/dxf")}>{t("mine.export_dxf")}</Action>
      <Action onClick={() => download("/api/mine/export/str")}>STR</Action>
      <Action onClick={() => download("/api/mine/export/csv")}>CSV</Action>
      <Action className="primary" disabled={!shiftsOk} onClick={async () => { setErr(null); try { await api.put("/api/mine/config", cfg); setOk(t("common.saved")); reload(); } catch (e) { setErr(e); } }}>{t("common.save")}</Action>
    </>}>
      {ok && <div className="success">{ok}</div>}<ErrorBox error={err} />
      <ShiftsEditor value={cfg.shifts} onChange={(v) => { setOk(""); set("shifts", v); }} onValid={setShiftsOk} />
      <div className="grid g2">
        <Card title={t("mine.general")}>
          <div className="form">
            <Field label={t("common.name")}><input value={cfg.name} onChange={(e) => set("name", e.target.value)} /></Field>
            <Field label={t("mine.country")}><input value={cfg.country || ""} onChange={(e) => set("country", e.target.value)} /></Field>
            <Field label={t("mine.timezone")}><input value={cfg.timezone} onChange={(e) => set("timezone", e.target.value)} /></Field>
            <Field label={t("mine.currency")}><input value={cfg.currency} onChange={(e) => set("currency", e.target.value)} /></Field>
            <Field label={t("mine.coordinate_system")}><input value={cfg.coordinate_system || ""} onChange={(e) => set("coordinate_system", e.target.value)} /></Field>
            <Field label={t("mine.collar")}><Num value={cfg.collar_elevation} onChange={(v) => set("collar_elevation", v)} /></Field>
            <Field label={t("mine.sublevel_height")}><select value={[20, 25, 30].includes(cfg.sublevel_height) ? cfg.sublevel_height : "own"} onChange={(e) => e.target.value !== "own" && set("sublevel_height", Number(e.target.value))}>{[20, 25, 30].map((h) => <option key={h} value={h}>{h} {t("units.m")}</option>)}<option value="own">{t("mine.own")}</option></select></Field>
            <Field label={t("mine.sublevel_own")}><Num value={cfg.sublevel_height} onChange={(v) => set("sublevel_height", v)} /></Field>
            <Field label={t("mine.xc_spacing")}><Num value={cfg.xc_spacing} onChange={(v) => set("xc_spacing", v)} /></Field>
            <Field label={t("mine.fwd_offset")}><Num value={cfg.fwd_offset} onChange={(v) => set("fwd_offset", v)} /></Field>
            <Field label={t("mine.ore_density")}><Num value={cfg.densities?.ore} onChange={(v) => set("densities", { ...cfg.densities, ore: v })} /></Field>
            <Field label={t("mine.waste_density")}><Num value={cfg.densities?.waste} onChange={(v) => set("densities", { ...cfg.densities, waste: v })} /></Field>
            <Field label={t("mine.haulage_cost")}><Num value={cfg.costs?.haulage_per_t} onChange={(v) => set("costs", { ...cfg.costs, haulage_per_t: v })} /></Field>
            <Field label={t("mine.processing_cost")}><Num value={cfg.costs?.processing_per_t} onChange={(v) => set("costs", { ...cfg.costs, processing_per_t: v })} /></Field>
          </div>
          <h3>{t("mine.edd_template")}</h3>
          <Field label={t("mine.edd_template_hint")}><input value={cfg.edd_template || ""} placeholder="{hole};{det};{delay}" onChange={(e) => set("edd_template", e.target.value)} /></Field>
        </Card>
        <Card title={t("mine.sections")}>
          <table className="t"><thead><tr><th>{t("workings.type")}</th><th>{t("dev_passport.section")}</th><th>{t("dev_passport.width")}</th><th>{t("dev_passport.height")}</th><th>{t("dev_passport.arch_height")}</th><th>{t("mine.std_passport")}</th></tr></thead>
            <tbody>{TYPES.map((k) => { const s = cfg.sections?.[k] || {}; const upd = (f: string, v: any) => set("sections", { ...cfg.sections, [k]: { ...s, [f]: v } });
              return <tr key={k}><td>{t(`workings.types.${k}`)}</td>
                <td><select value={s.shape || "arch"} onChange={(e) => upd("shape", e.target.value)}>{["arch", "rect", "trapezoid", "horseshoe"].map((x) => <option key={x} value={x}>{t(`dev_passport.shapes.${x}`)}</option>)}</select></td>
                <td><Num value={s.width} onChange={(v) => upd("width", v)} style={{ width: 60 }} /></td><td><Num value={s.height} onChange={(v) => upd("height", v)} style={{ width: 60 }} /></td>
                <td><Num value={s.arch_height} onChange={(v) => upd("arch_height", v)} style={{ width: 60 }} /></td>
                <td><select value={cfg.standard_passports?.[k] || ""} onChange={(e) => set("standard_passports", { ...cfg.standard_passports, [k]: e.target.value })}><option value="">—</option>{(typ || []).map((p) => <option key={p.id} value={p.number}>{p.number}</option>)}</select></td></tr>; })}</tbody></table>
          <h3>{t("mine.name_templates")}</h3>
          {["ru", "en", "es"].map((lng) => <div key={lng} className="form" style={{ marginBottom: 6 }}>
            {["access", "fwd", "xc"].map((k) => <Field key={k} label={`${lng}: ${t(`workings.types.${k}`)}`}><input value={cfg.name_templates?.[lng]?.[k] || ""} onChange={(e) => set("name_templates", { ...cfg.name_templates, [lng]: { ...(cfg.name_templates?.[lng] || {}), [k]: e.target.value } })} /></Field>)}
          </div>)}
          <div className="small muted">{t("mine.templates_hint")}</div>
        </Card>
      </div>
      <Card title={t("mine.mines")}>
        <Table rows={list?.loaded} cols={[{ key: "code", title: t("mine.code") }, { key: "name", title: t("common.name") }, { key: "path", title: t("mine.path") },
          { key: "active", title: t("mine.active"), render: (m) => m.active ? "✓" : <Action className="small" onClick={async () => { await api.post(`/api/mine/activate/${m.id}`); reloadList(); reload(); window.location.reload(); }}>{t("mine.activate")}</Action> }]} />
        <div className="row" style={{ marginTop: 10 }}>
          <span className="muted small">{t("mine.packages")} ({list?.root}): </span>
          {(list?.packages || []).map((p: string) => <Action key={p} className="small" onClick={async () => { await api.post("/api/mine/load", { package: p }); reloadList(); }}>{t("mine.load")} {p}</Action>)}
          <label className="btn">{t("mine.upload_zip")}<input type="file" hidden accept=".zip" onChange={async (e) => { const f = e.target.files?.[0]; if (!f) return; const fd = new FormData(); fd.append("file", f); try { await api.upload("/api/mine/upload", fd); reloadList(); } catch (x) { setErr(x); } }} /></label>
        </div>
      </Card>
    </Page>
  );
}

export function ImportWizard() {
  const { t } = useTranslation();
  const [kind, setKind] = useState("workings");
  const [job, setJob] = useState<any>(null);
  const [map, setMap] = useState<Record<string, string>>({});
  const [off, setOff] = useState([0, 0, 0]);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const { data: jobs, reload } = useApi<any[]>("/api/mine/import/jobs");
  const types = ["ramp", "access", "fwd", "xc", "raise", "sump", "niche", "other", "skip"];
  return (
    <Page title={t("menu.import")}>
      <Card title={`1. ${t("import.upload")}`}>
        <div className="row">
          <Field label={t("import.kind")}><select value={kind} onChange={(e) => setKind(e.target.value)}>{["workings", "stopes", "orebody", "holes", "scan"].map((k) => <option key={k} value={k}>{t(`import.kinds.${k}`)}</option>)}</select></Field>
          <label className="btn">{t("import.choose_file")}<input type="file" hidden accept=".dxf,.dwg,.str,.dtm,.csv,.las,.laz,.e57,.ply,.xyz,.pts,.obj,.stl,.xml" onChange={async (e) => {
            const f = e.target.files?.[0]; if (!f) return;
            setErr(null); setRes(null);
            const fd = new FormData(); fd.append("file", f); fd.append("kind", kind);
            try { const j = await api.upload("/api/mine/import/upload", fd); setJob(j); setMap(j.layers_suggested || {}); reload(); } catch (x) { setErr(x); }
          }} /></label>
          <span className="muted small">{t("import.formats")}</span>
        </div>
        <ErrorBox error={err} />
      </Card>
      {job && <>
        <Card title={`2. ${t("import.layers")}`}>
          <div className="small muted">{job.fmt} · {t(`import.parsed.${job.kind}`, { defaultValue: job.kind })} {job.count ? `· ${job.count}` : ""}</div>
          {Object.keys(map).length > 0 && <table className="t"><thead><tr><th>{t("import.layer")}</th><th>{t("import.as_type")}</th></tr></thead>
            <tbody>{Object.entries(map).map(([lay, tp]) => <tr key={lay}><td>{lay}</td><td><select value={tp} onChange={(e) => setMap({ ...map, [lay]: e.target.value })}>{types.map((x) => <option key={x} value={x}>{x === "skip" ? t("import.skip") : t(`workings.types.${x}`)}</option>)}</select></td></tr>)}</tbody></table>}
        </Card>
        <Card title={`3. ${t("import.coords")}`}>
          <div className="small">{t("import.bbox")}: {job.bbox ? `${job.bbox.min.join(", ")} … ${job.bbox.max.join(", ")}` : "—"}</div>
          <div className="form">{["dX", "dY", "dZ"].map((c, i) => <Field key={c} label={c}><Num value={off[i]} onChange={(v) => { const o = [...off]; o[i] = v || 0; setOff(o); }} /></Field>)}</div>
        </Card>
        <Card title={`4. ${t("import.preview3d")}`}>
          <Scene3D height={420} polylines={(job.preview?.polylines || []).map((p: any) => ({ points: p.points.map((q: number[]) => [q[0] + off[0], q[1] + off[1], q[2] + off[2]]), color: map[p.layer] === "skip" ? 0x555555 : 0xf4a261 }))}
            points={(job.preview?.points || []).map((q: number[]) => [q[0] + off[0], q[1] + off[1], q[2] + off[2]])} />
        </Card>
        <Card title={`5. ${t("import.do_import")}`}>
          {["workings", "orebody"].includes(kind) ? <Action className="primary" onClick={async () => { try { setRes(await api.post(`/api/mine/import/${job.job_id}/commit`, { kind, layer_map: map, offset: off })); reload(); } catch (e) { setErr(e); } }}>{t("import.do_import")}</Action>
            : <div className="notice">{t("import.use_workflow")}</div>}
          {res && <div className="success">{t("import.created", { n: res.created })}</div>}
        </Card>
      </>}
      <Card title={t("import.jobs")}>
        <Table rows={jobs} cols={[{ key: "ts", title: t("common.time"), render: (j) => j.ts.slice(0, 16).replace("T", " ") }, { key: "username", title: t("common.user") }, { key: "filename", title: t("import.file") },
          { key: "fmt", title: t("import.format") }, { key: "kind", title: t("import.kind"), render: (j) => t(`import.kinds.${j.kind}`) }, { key: "status", title: t("common.status") }, { key: "summary", title: t("import.summary"), render: (j) => j.summary?.created ?? (j.summary?.layers || []).length }]} />
      </Card>
    </Page>
  );
}
