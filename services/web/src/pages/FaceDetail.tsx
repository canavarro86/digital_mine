import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import AiPanel from "../components/AiPanel";
import FaceSvg from "../components/FaceSvg";
import { Action, Badge, Card, ErrorBox, Page, Stat, Table, Tabs } from "../components/ui";
import { api, download } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { fmtNum } from "../lib/i18n";

const DEV_FLOW = ["ready", "drilling", "drilled", "recalculated", "handed", "accepted", "charged", "wait_blast", "blasted", "ventilation", "mucking", "scaling", "support", "surveyed", "analyzed"];
const STOPE_FLOW = ["ready", "drilling", "drilled", "recalculated", "handed", "accepted", "charged", "wait_blast", "blasted", "draw", "cms", "analyzed"];

function Steps({ face }: { face: any }) {
  const { t } = useTranslation();
  const flow = face.kind === "dev" ? DEV_FLOW : STOPE_FLOW;
  const i = flow.indexOf(face.status);
  return <div className="steps">{flow.map((s, k) => <span key={s} className={k < i ? "done" : k === i ? "cur" : ""}>{t(`workflow.status.${s}`)}</span>)}</div>;
}

/** Ввод фактических данных бурения: файл со станка/флешки или по шпурам вручную. */
function DrillInput({ face, onDone }: { face: any; onDone: () => void }) {
  const { t } = useTranslation();
  const plan: any[] = face.kind === "dev"
    ? (face.passport?.design?.holes || []).filter((h: any) => h.type !== "empty")
    : (face.rings?.design?.rings || []).flatMap((r: any) => r.holes.map((h: any) => ({ ...h, ring: r.no })));
  const [rows, setRows] = useState<any[]>(() => plan.map((h) => ({ id: h.id, ring: h.ring, type: h.type, length: h.length, dx: 0, dy: 0, deviation_pct: 0, drilled: true })));
  const [err, setErr] = useState<unknown>(null);
  const { data: fleet } = useApi<any[]>("/api/fleet");
  const { data: staff } = useApi<any[]>("/api/staff");
  const [mid, setMid] = useState("");
  const [pid, setPid] = useState("");
  const upd = (i: number, k: string, v: any) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const send = async () => {
    try {
      const holes = face.kind === "dev"
        ? rows.map((r) => { const d = plan.find((h) => h.id === r.id); return { id: r.id, length: Number(r.length), drilled: r.drilled, toe_x: d.x + Number(r.dx || 0), toe_y: d.y + Number(r.dy || 0) }; })
        : rows.map((r) => ({ ring: r.ring, id: r.id, length: Number(r.length), deviation_pct: Number(r.deviation_pct || 0), drilled: r.drilled, status: r.drilled ? "drilled" : "blocked" }));
      await api.post(`/api/workflow/faces/${face.id}/drill-report`, { holes, source: "manual", machine_id: Number(mid) || null, person_id: Number(pid) || null });
      onDone();
    } catch (e) { setErr(e); }
  };
  return (
    <div>
      <div className="row" style={{ marginBottom: 8 }}>
        <label className="btn">{t("workflow.upload_drill_file")}<input type="file" hidden accept=".csv,.xml,.iredes" onChange={async (e) => {
          const f = e.target.files?.[0];
          if (!f) return;
          const fd = new FormData(); fd.append("file", f);
          if (mid) fd.append("machine_id", mid);
          if (pid) fd.append("person_id", pid);
          try { await api.upload(`/api/workflow/faces/${face.id}/drill-report/file`, fd); onDone(); } catch (x) { setErr(x); }
        }} /></label>
        <select value={mid} onChange={(e) => setMid(e.target.value)}><option value="">{t("board.machine")}</option>{(fleet || []).filter((m) => m.type === (face.kind === "dev" ? "dev_drill" : "ring_drill")).map((m) => <option key={m.id} value={m.id}>{m.number}</option>)}</select>
        <select value={pid} onChange={(e) => setPid(e.target.value)}><option value="">{t("board.person")}</option>{(staff || []).filter((p) => p.profession === "driller").map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}</select>
        <span className="muted small">{t("workflow.manual_hint")}</span>
      </div>
      <div className="tbl-wrap" style={{ maxHeight: 340 }}>
        <table className="t"><thead><tr>
          {face.kind === "stope" && <th>{t("ring.ring")}</th>}<th>№</th><th>{t("dev_passport.type")}</th><th>{t("dev_passport.length_m")}</th>
          {face.kind === "dev" ? <><th>Δx, {t("units.m")}</th><th>Δy, {t("units.m")}</th></> : <th>{t("workflow.deviation_pct")}</th>}<th>{t("workflow.drilled")}</th>
        </tr></thead><tbody>
          {rows.map((r, i) => <tr key={`${r.ring}-${r.id}`}>
            {face.kind === "stope" && <td>{r.ring}</td>}<td>{r.id}</td><td>{r.type ? t(`dev_passport.hole_types.${r.type}`) : ""}</td>
            <td><input style={{ width: 70 }} type="number" step="0.01" value={r.length} onChange={(e) => upd(i, "length", e.target.value)} /></td>
            {face.kind === "dev" ? <><td><input style={{ width: 60 }} type="number" step="0.01" value={r.dx} onChange={(e) => upd(i, "dx", e.target.value)} /></td>
              <td><input style={{ width: 60 }} type="number" step="0.01" value={r.dy} onChange={(e) => upd(i, "dy", e.target.value)} /></td></>
              : <td><input style={{ width: 60 }} type="number" step="0.1" value={r.deviation_pct} onChange={(e) => upd(i, "deviation_pct", e.target.value)} /></td>}
            <td><input type="checkbox" checked={r.drilled} onChange={(e) => upd(i, "drilled", e.target.checked)} /></td>
          </tr>)}
        </tbody></table>
      </div>
      <ErrorBox error={err} />
      <div className="row" style={{ marginTop: 8 }}><button className="primary" onClick={send}>{t("workflow.send_drill_report")}</button></div>
    </div>
  );
}

function ChargeInput({ face, onDone }: { face: any; onDone: () => void }) {
  const { t } = useTranslation();
  const src = face.recalc?.result || (face.kind === "dev" ? face.passport?.design : face.rings?.design);
  const plan: any[] = useMemo(() => face.kind === "dev"
    ? (src?.holes || []).filter((h: any) => h.type !== "empty" && !h.not_drilled)
    : (src?.rings || []).flatMap((r: any) => r.holes.filter((h: any) => h.status !== "blocked").map((h: any) => ({ ...h, ring: r.no }))), [src]);
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => setRows(plan.map((h) => ({ id: h.id, ring: h.ring, explosive: h.explosive || "", kg: h.charge_kg, length: h.charge_length, stemming: h.stemming, detonator: `EDD-${String(h.id).padStart(3, "0")}`, delay_ms: h.delay_ms, status: "charged" }))), [plan]);
  const [err, setErr] = useState<unknown>(null);
  const upd = (i: number, k: string, v: any) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  return (
    <div>
      <div className="tbl-wrap" style={{ maxHeight: 340 }}>
        <table className="t"><thead><tr>
          {face.kind === "stope" && <th>{t("ring.ring")}</th>}<th>№</th><th>{t("explosives.explosive")}</th><th>{t("units.kg")}</th><th>{t("workflow.charge_length")}</th><th>{t("dev_passport.stemming_m")}</th><th>{t("workflow.detonator")}</th><th>{t("dev_passport.delay_ms")}</th><th>{t("common.status")}</th>
        </tr></thead><tbody>
          {rows.map((r, i) => <tr key={`${r.ring}-${r.id}`}>
            {face.kind === "stope" && <td>{r.ring}</td>}<td>{r.id}</td><td className="small">{r.explosive}</td>
            <td><input style={{ width: 70 }} type="number" step="0.1" value={r.kg} onChange={(e) => upd(i, "kg", Number(e.target.value))} /></td>
            <td>{fmtNum(r.length, 2)}</td><td>{fmtNum(r.stemming, 2)}</td>
            <td><input style={{ width: 90 }} value={r.detonator} onChange={(e) => upd(i, "detonator", e.target.value)} /></td>
            <td><input style={{ width: 70 }} type="number" value={r.delay_ms ?? ""} onChange={(e) => upd(i, "delay_ms", Number(e.target.value))} /></td>
            <td><select value={r.status} onChange={(e) => upd(i, "status", e.target.value)}>{["charged", "not_charged", "misfire"].map((s) => <option key={s} value={s}>{t(`workflow.charge_status.${s}`)}</option>)}</select></td>
          </tr>)}
        </tbody></table>
      </div>
      <ErrorBox error={err} />
      <div className="row" style={{ marginTop: 8 }}><button className="primary" onClick={async () => {
        try { await api.post(`/api/workflow/faces/${face.id}/charge-log`, { holes: rows }); onDone(); } catch (e) { setErr(e); }
      }}>{t("workflow.save_charge_log")}</button></div>
    </div>
  );
}

export function AnalysisView({ a }: { a: any }) {
  const { t } = useTranslation();
  if (!a) return null;
  const r = a.result || a;
  const causes = r.causes || {};
  return (
    <div>
      {r.kind === "dev" ? <div className="grid g4">
        <Stat label={t("analysis.kish")} value={fmtNum(r.kish, 2)} />
        <Stat label={t("analysis.advance")} value={`${fmtNum(r.advance, 2)} / ${fmtNum(r.design_advance, 2)}`} unit={t("units.m")} />
        <Stat label={t("analysis.overbreak")} value={fmtNum(r.overbreak_pct)} unit="%" />
        <Stat label={t("analysis.half_cast")} value={fmtNum(r.half_cast_pct, 0)} unit="%" />
        <Stat label={t("analysis.extra_m3")} value={fmtNum(r.extra_m3)} unit={t("units.m3")} />
        <Stat label={t("analysis.extra_t")} value={fmtNum(r.extra_t)} unit={t("units.t")} />
        <Stat label={t("analysis.extra_cost")} value={fmtNum(r.extra_cost, 0)} unit={r.currency} />
        <Stat label={t("analysis.explosive")} value={`${fmtNum(r.explosive_fact_kg, 0)} / ${fmtNum(r.explosive_plan_kg, 0)}`} unit={t("units.kg")} />
      </div> : <div className="grid g4">
        <Stat label={t("analysis.blasted_t")} value={fmtNum(r.blasted_t, 0)} unit={t("units.t")} />
        <Stat label={t("analysis.dilution")} value={`${fmtNum(r.dilution_t, 0)} ${t("units.t")} · ${fmtNum(r.dilution_pct)}%`} />
        <Stat label={t("analysis.losses")} value={`${fmtNum(r.loss_t, 0)} ${t("units.t")} · ${fmtNum(r.loss_pct)}%`} />
        <Stat label={t("analysis.elos")} value={`${fmtNum(r.elos_hw, 2)} / ${fmtNum(r.elos_fw, 2)}`} unit={t("units.m")} />
        <Stat label={t("analysis.result_usd")} value={fmtNum(r.result_usd, 0)} unit={r.currency} />
        <Stat label={t("analysis.loss_cost")} value={fmtNum(r.loss_cost_usd, 0)} unit={r.currency} />
        <Stat label={t("analysis.dilution_cost")} value={fmtNum(r.dilution_cost_usd, 0)} unit={r.currency} />
        <Stat label={t("analysis.explosive")} value={`${fmtNum(r.explosive_fact_kg, 0)} / ${fmtNum(r.explosive_plan_kg, 0)}`} unit={t("units.kg")} />
      </div>}
      <h3>{t("analysis.causes_title")}: <Badge value={t(`analysis.causes.${r.primary_cause}`)} /></h3>
      <div className="row">{Object.entries(r.groups || {}).map(([g, v]) => <span key={g} className="badge info">{t(`analysis.groups.${g}`)}: {Math.round(Number(v) * 100)}%</span>)}</div>
      <div className="small" style={{ marginTop: 6 }}>{Object.entries(causes).map(([c, v]) => `${t(`analysis.causes.${c}`)} ${Math.round(Number(v) * 100)}%`).join(" · ")}</div>
      {a.scenario?.expected && <div className="small muted">{t("analysis.scenario_ref")}: {t(`analysis.causes.${a.scenario.expected}`)} {a.scenario.expected === r.primary_cause ? "✓" : "✗"}</div>}
    </div>
  );
}

export default function FaceDetail() {
  const { id } = useParams();
  const { t, i18n } = useTranslation();
  const { can, timeMode } = useAuth();
  const { data: f, reload, error } = useApi<any>(`/api/workflow/faces/${id}`, 15000, [id]);
  const [tab, setTab] = useState("cycle");
  if (!f) return <ErrorBox error={error} />;
  const design = f.recalc?.result || f.passport?.design;
  const rc = f.recalc?.result?.recalc;
  return (
    <Page title={<>{f.name} <Badge value={f.status} group="workflow.status" /></>} actions={<>
      {f.next.filter((n: any) => n.status !== "wait_blast").map((n: any) => <Action key={n.status} className="primary" disabled={!n.allowed} onClick={async () => {
        const url = `/api/workflow/faces/${f.id}/transition`;
        try { await api.post(url, { to: n.status }); } catch (e: any) {
          // вне окна ВР администратор может взорвать с обязательной причиной (пишется в журнал)
          if (e?.code !== "errors.blast_override_reason") throw e;
          const reason = window.prompt(String(t("workflow.blast_override_prompt", e.params || {})))?.trim();
          if (!reason) throw e;
          await api.post(url, { to: n.status, override_reason: reason });
        }
        reload();
      }}>→ {t(`workflow.status.${n.status}`)}</Action>)}
      {f.passport && <Link to={`/passports/${f.passport.id}`}><button>{t("workflow.open_passport")}</button></Link>}
      {f.rings && <Link to={`/rings/${f.rings.id}`}><button>{t("workflow.open_rings")}</button></Link>}
      <Action onClick={() => download(`/api/reports/export/face/pdf?id=${f.id}&lang=${i18n.language}`)}>{t("reports.pdf")}</Action>
    </>}>
      <Steps face={f} />
      <div className="row small muted" style={{ marginBottom: 10 }}>
        {t("workflow.cycle")} {f.cycle_no} · {f.working ? `${f.working.name} · ${f.chainage_label} / ${fmtNum(f.working.length)} ${t("units.m")}` : f.stope?.name} · {t("workflow.since")} {timeMode === "mine" ? f.since_mine : f.since_user}
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[["cycle", t("workflow.tab_cycle")], ["history", t("workflow.tab_history")]]} />
      {tab === "cycle" && <>
        <div className="grid g2">
          <Card title={t("workflow.drill_report")}>
            {f.drill_report ? <div>
              <div className="kv">
                <div>{t("workflow.source")}</div><div>{t(`workflow.sources.${f.drill_report.source}`)}</div>
                <div>{t("workflow.drilled")}</div><div>{f.drill_report.summary.drilled} / {f.drill_report.summary.holes}</div>
                <div>{t("dev_passport.drill_m")}</div><div>{fmtNum(f.drill_report.summary.drill_m)}</div>
                <div>{t("workflow.mean_dev")}</div><div>{fmtNum(f.drill_report.summary.mean_deviation_pct, 2)} %</div>
              </div>
            </div> : can("workflow.transition") && ["ready", "drilling"].includes(f.status) ? <DrillInput face={f} onDone={reload} /> : <span className="muted">{t("workflow.no_report")}</span>}
          </Card>
          <Card title={t("workflow.recalc")} actions={f.drill_report && can("recalc.edit") && <>
            <Action className="small" onClick={async () => { await api.post(`/api/workflow/faces/${f.id}/recalc`); reload(); }}>{t("workflow.do_recalc")}</Action>
            {f.recalc && <Action className="small" onClick={() => download(`/api/workflow/faces/${f.id}/edd.csv`)}>{t("workflow.edd_file")}</Action>}
          </>}>
            {rc ? <div className="kv">
              <div>{t("workflow.not_drilled")}</div><div>{(rc.not_drilled || []).length || rc.blocked || 0}</div>
              {f.kind === "dev" && <><div>{t("workflow.zone.overloaded")}</div><div>{rc.overloaded}</div>
                <div>{t("workflow.zone.underloaded")}</div><div>{rc.underloaded}</div>
                <div>{t("workflow.mean_dev_m")}</div><div>{fmtNum(rc.mean_deviation_m, 3)}</div></>}
              <div>{t("workflow.expl_design")}</div><div>{fmtNum(rc.explosive_design_kg)} {t("units.kg")}</div>
              <div>{t("workflow.expl_recommended")}</div><div>{fmtNum(rc.explosive_recommended_kg)} {t("units.kg")}</div>
            </div> : <span className="muted">{t("workflow.no_recalc")}</span>}
            {f.recalc && can("ai.use") && <AiPanel module="dev_recalc" entityId={f.recalc.id} />}
          </Card>
        </div>
        {f.kind === "dev" && design && <Card title={rc ? t("workflow.actual_view") : t("dev_passport.face_view")}>
          <FaceSvg result={design} actual={!!rc} size={520} />
        </Card>}
        <div className="grid g2">
          <Card title={t("workflow.charge_log")}>
            {f.charge_log ? <div className="kv">
              <div>{t("workflow.charged")}</div><div>{f.charge_log.summary.charged} / {f.charge_log.summary.holes}</div>
              <div>{t("workflow.misfires")}</div><div>{f.charge_log.summary.misfires}</div>
              <div>{t("workflow.plan_fact")}</div><div>{fmtNum(f.charge_log.summary.plan_kg)} / {fmtNum(f.charge_log.summary.fact_kg)} {t("units.kg")} ({fmtNum(f.charge_log.summary.over_pct)}%)</div>
            </div> : can("workflow.blast") && f.status === "accepted" ? <ChargeInput face={f} onDone={reload} /> : <span className="muted">{t("workflow.no_charge")}</span>}
          </Card>
          <Card title={t("workflow.scan")}>
            {f.scan ? <div className="kv"><div>{t("workflow.scan_kind")}</div><div>{f.scan.kind}</div><div>{t("common.time")}</div><div>{f.scan.created_at}</div></div>
              : can("workflow.transition") ? <label className="btn">{t("workflow.upload_scan")}<input type="file" hidden accept=".las,.laz,.e57,.ply,.xyz,.pts,.txt" onChange={async (e) => {
                const file = e.target.files?.[0]; if (!file) return;
                const fd = new FormData(); fd.append("file", file);
                await api.upload(`/api/workflow/faces/${f.id}/scan/file`, fd); reload();
              }} /></label> : null}
          </Card>
        </div>
        <Card title={t("workflow.analysis")} actions={f.scan && !f.analysis && can("recalc.edit") && <Action className="primary small" onClick={async () => { await api.post(`/api/workflow/faces/${f.id}/analyze`); reload(); }}>{t("workflow.do_analyze")}</Action>}>
          {f.analysis ? <><AnalysisView a={f.analysis} />{can("ai.use") && <AiPanel module={f.kind === "dev" ? "dev_cycle" : "stope_result"} entityId={f.analysis.id} />}</> : <span className="muted">{t("workflow.no_analysis")}</span>}
        </Card>
      </>}
      {tab === "history" && <>
        <Card title={t("workflow.events")}>
          <Table rows={f.events} cols={[
            { key: "ts", title: t("common.time"), render: (e) => timeMode === "mine" ? e.ts_mine : e.ts_user },
            { key: "cycle_no", title: t("workflow.cycle"), num: true },
            { key: "from_status", title: t("workflow.from"), render: (e) => t(`workflow.status.${e.from_status}`) },
            { key: "to_status", title: t("workflow.to"), render: (e) => t(`workflow.status.${e.to_status}`) },
            { key: "username", title: t("common.user") },
            { key: "comment", title: t("common.comment") },
          ]} />
        </Card>
        <Card title={t("workflow.cycles")}>
          <Table rows={f.history} cols={[
            { key: "cycle_no", title: t("workflow.cycle"), num: true },
            { key: "kish", title: t("analysis.kish"), num: true, render: (a) => fmtNum(a.result.kish, 2) },
            { key: "advance", title: t("analysis.advance"), num: true, render: (a) => fmtNum(a.result.advance, 2) },
            { key: "ob", title: t("analysis.overbreak"), num: true, render: (a) => fmtNum(a.result.overbreak_pct ?? a.result.dilution_pct) },
            { key: "extra", title: t("analysis.extra_t"), num: true, render: (a) => fmtNum(a.result.extra_t ?? a.result.dilution_t) },
            { key: "cost", title: t("analysis.extra_cost"), num: true, render: (a) => fmtNum(a.result.extra_cost ?? a.result.result_usd, 0) },
            { key: "cause", title: t("analysis.cause"), render: (a) => t(`analysis.causes.${a.causes.primary}`) },
          ]} />
        </Card>
      </>}
    </Page>
  );
}
