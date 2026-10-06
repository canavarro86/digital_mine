import { useState, Fragment } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { AiAnswer } from "../components/AiPanel";
import AiPanel from "../components/AiPanel";
import { Action, Badge, Card, ErrorBox, Modal, Page, Stat, Table, Tabs } from "../components/ui";
import { api, download, qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { fmtNum } from "../lib/i18n";

export function Analysis() {
  const { t } = useTranslation();
  const [kind, setKind] = useState("");
  const { data } = useApi<any[]>("/api/workflow/analyses" + qs({ kind, limit: 300 }), 30000, [kind]);
  const { data: chk } = useApi<any>("/api/workflow/scenario-check", 30000);
  return (
    <Page title={t("menu.analysis")} actions={<select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">{t("common.all")}</option><option value="dev">{t("common.kind.dev")}</option><option value="stope">{t("common.kind.stope")}</option></select>}>
      {chk && chk.total > 0 && <Card title={t("analysis.scenario_check")}>
        <div className="grid g4">
          <Stat label={t("analysis.checked")} value={chk.total} /><Stat label={t("analysis.correct")} value={chk.correct} />
          <Stat label={t("analysis.accuracy")} value={fmtNum(chk.accuracy * 100, 0)} unit="%" />
        </div>
        <div className="row" style={{ marginTop: 8 }}>{Object.entries(chk.by_cause).map(([c, v]: any) => <span key={c} className={`badge ${v.ok / v.total >= 0.8 ? "ok" : "warn"}`}>{t(`analysis.causes.${c}`)}: {v.ok}/{v.total}</span>)}</div>
      </Card>}
      <Card>
        <Table rows={data} cols={[
          { key: "created_at", title: t("common.time"), render: (a) => a.created_at.slice(0, 16).replace("T", " ") },
          { key: "face_name", title: t("workflow.face"), render: (a) => <Link to={`/faces/${a.face_id}`}>{a.face_name}</Link> },
          { key: "cycle_no", title: t("workflow.cycle"), num: true },
          { key: "kish", title: t("analysis.kish"), num: true, render: (a) => fmtNum(a.result.kish, 2) },
          { key: "ob", title: t("analysis.overbreak_dilution"), num: true, render: (a) => fmtNum(a.result.overbreak_pct ?? a.result.dilution_pct) },
          { key: "extra", title: t("analysis.extra_t"), num: true, render: (a) => fmtNum(a.result.extra_t ?? a.result.dilution_t, 0) },
          { key: "elos", title: "ELOS", num: true, render: (a) => a.kind === "stope" ? fmtNum(a.result.elos_hw, 2) : "" },
          { key: "usd", title: "USD", num: true, render: (a) => fmtNum(a.result.extra_cost ?? a.result.result_usd, 0) },
          { key: "cause", title: t("analysis.cause"), render: (a) => <Badge value={t(`analysis.causes.${a.causes.primary}`)} /> },
          { key: "groups", title: t("analysis.groups_title"), render: (a) => Object.entries(a.causes.groups || {}).filter(([, v]) => Number(v) > 0).map(([g, v]) => `${t(`analysis.groups.${g}`)} ${Math.round(Number(v) * 100)}%`).join(" · ") },
          { key: "ref", title: t("analysis.scenario_ref"), render: (a) => a.scenario?.expected ? <span>{t(`analysis.causes.${a.scenario.expected}`)} {a.scenario.expected === a.causes.primary ? "✓" : "✗"}</span> : "" },
        ]} />
      </Card>
    </Page>
  );
}

export function Reports() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [tab, setTab] = useState("period");
  const [period, setPeriod] = useState("shift");
  const [day, setDay] = useState("");
  const [lang, setLang] = useState(i18n.language);
  const [ent, setEnt] = useState<any>({});
  const { data: rep } = useApi<any>(tab === "period" ? "/api/reports/period" + qs({ period, day }) : null, 0, [tab, period, day]);
  const { data: faces } = useApi<any[]>("/api/workflow/faces");
  const { data: fleet } = useApi<any[]>("/api/fleet");
  const { data: staff } = useApi<any[]>("/api/staff");
  const path = tab === "face" ? `/api/reports/face/${ent.face}` : tab === "machine" ? `/api/reports/machine/${ent.machine}` : tab === "person" ? `/api/reports/person/${ent.person}` : null;
  const { data: one } = useApi<any>(path && ent[tab] ? path : null, 0, [path, ent[tab]]);
  const id = ent[tab];
  const [upFace, setUpFace] = useState("");
  const [upMsg, setUpMsg] = useState<any>(null);
  return (
    <Page title={t("menu.reports")} actions={<>
      <select value={lang} onChange={(e) => setLang(e.target.value)}>{["ru", "en", "es"].map((l) => <option key={l}>{l}</option>)}</select>
      <Action className="primary" onClick={() => download(`/api/reports/shift-zip?lang=${lang}${day ? `&day=${day}` : ""}`)}>{t("reports.shift_zip")}</Action>
    </>}>
      <Tabs value={tab} onChange={setTab} tabs={[["period", t("reports.by_period")], ["face", t("reports.by_face")], ["machine", t("reports.by_machine")], ["person", t("reports.by_person")], ["upload", t("reports.upload_drill")]]} />
      {tab === "period" && <Card actions={<>
        <select value={period} onChange={(e) => setPeriod(e.target.value)}>{["shift", "day", "month"].map((p) => <option key={p} value={p}>{t(`reports.period.${p}`)}</option>)}</select>
        <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        <Action onClick={() => download(`/api/reports/export/period/pdf?period=${period}&lang=${lang}${day ? `&day=${day}` : ""}`)}>PDF</Action>
        <Action onClick={() => download(`/api/reports/export/period/csv?period=${period}&lang=${lang}${day ? `&day=${day}` : ""}`)}>CSV</Action>
        {can("ai.use") && <AiPanel module="mine_summary" entityId={period === "month" ? "month" : "day"} />}
      </>} title={rep ? `${t(`reports.period.${rep.period}`)}: ${rep.label}` : ""}>
        {rep && <>
          <div className="grid g4">
            <Stat label={t("reports.dev_advance")} value={fmtNum(rep.development.advance_m)} unit={t("units.m")} />
            <Stat label={t("reports.kish")} value={fmtNum(rep.development.kish, 2)} />
            <Stat label={t("reports.extra_t")} value={fmtNum(rep.development.extra_t, 0)} unit={t("units.t")} />
            <Stat label={t("reports.extra_cost")} value={fmtNum(rep.development.extra_cost, 0)} unit="USD" />
            <Stat label={t("reports.stope_t")} value={fmtNum(rep.stoping.blasted_t, 0)} unit={t("units.t")} />
            <Stat label={t("reports.elos")} value={fmtNum(rep.stoping.elos_hw, 2)} unit={t("units.m")} />
            <Stat label={t("reports.dilution")} value={fmtNum(rep.stoping.dilution_pct)} unit="%" />
            <Stat label={t("reports.losses_usd")} value={fmtNum(rep.stoping.loss_cost, 0)} unit="USD" />
            <Stat label={t("reports.expl_plan")} value={fmtNum(rep.explosives.plan_kg, 0)} unit={t("units.kg")} />
            <Stat label={t("reports.expl_fact")} value={fmtNum(rep.explosives.fact_kg, 0)} unit={t("units.kg")} />
            <Stat label={t("reports.blasted_in_window")} value={`${rep.blasting.dev_in_window} / ${rep.blasting.stope_in_window}`} />
            <Stat label={t("reports.moved_to_next")} value={rep.blasting.moved_to_next} />
            {rep.blasting.outside_window > 0 && <Stat label={t("reports.blasted_outside")} value={rep.blasting.outside_window} />}
          </div>
          <h3>{t("reports.details")}</h3>
          <Table rows={rep.cycles} cols={["face", "cycle", "advance", "kish", "overbreak_pct", "extra_t", "extra_cost", "elos_hw", "dilution_pct"].map((k) => ({ key: k, title: t(`reports.col.${k}`), num: k !== "face", render: k === "face" ? undefined : (r: any) => fmtNum(r[k], 2) }))
            .concat([{ key: "cause", title: t("reports.col.cause"), num: false, render: (r: any) => r.cause ? t(`analysis.causes.${r.cause}`) : "" }])} />
        </>}
      </Card>}
      {["face", "machine", "person"].includes(tab) && <Card actions={<>
        <select value={id || ""} onChange={(e) => setEnt({ ...ent, [tab]: e.target.value })}><option value="">—</option>
          {(tab === "face" ? faces : tab === "machine" ? fleet : staff)?.map((x: any) => <option key={x.id} value={x.id}>{x.name || x.number || x.full_name}</option>)}</select>
        {id && <><Action onClick={() => download(`/api/reports/export/${tab}/pdf?id=${id}&lang=${lang}`)}>PDF</Action><Action onClick={() => download(`/api/reports/export/${tab}/csv?id=${id}&lang=${lang}`)}>CSV</Action></>}
      </>}>
        {one && tab === "face" && <><div className="row">{Object.entries(one.totals).map(([k, v]) => <span key={k} className="badge">{t(`reports.tot.${k}`)}: {fmtNum(v, 2)}</span>)}</div>
          <Table rows={one.cycles} cols={["cycle", "advance", "kish", "overbreak_pct", "extra_t", "extra_cost", "explosive_plan_kg", "explosive_fact_kg"].map((k) => ({ key: k, title: t(`reports.col.${k}`), num: true, render: (r: any) => fmtNum(r[k], 2) })).concat([{ key: "cause", title: t("reports.col.cause"), num: false, render: (r: any) => r.cause ? t(`analysis.causes.${r.cause}`) : "" }])} /></>}
        {one && tab === "machine" && <><div className="row">{Object.entries(one.totals).map(([k, v]) => <span key={k} className="badge">{t(`reports.tot.${k}`)}: {fmtNum(v, 2)}</span>)}<span className="badge">{t("fleet.engine_hours")}: {one.engine_hours}</span></div>
          <Table rows={one.reports} cols={["face", "cycle", "drill_m", "drilled", "not_drilled", "mean_deviation_pct"].map((k) => ({ key: k, title: t(`reports.col.${k}`) }))} /></>}
        {one && tab === "person" && <div className="kv">{Object.entries(one).map(([k, v]) => <Fragment key={k}><div>{t(`reports.tot.${k}`, { defaultValue: k })}</div><div>{Array.isArray(v) ? v.join(", ") : typeof v === "number" ? fmtNum(v, 2) : String(v)}</div></Fragment>)}</div>}
      </Card>}
      {tab === "upload" && <Card title={t("reports.upload_drill")}>
        <div className="row">
          <select value={upFace} onChange={(e) => setUpFace(e.target.value)}><option value="">{t("workflow.face")}</option>{(faces || []).filter((f) => ["ready", "drilling"].includes(f.status)).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select>
          <label className="btn">{t("reports.choose_drill_file")}<input type="file" hidden accept=".csv,.xml,.iredes" disabled={!upFace} onChange={async (e) => {
            const f = e.target.files?.[0]; if (!f) return; const fd = new FormData(); fd.append("file", f);
            try { const r = await api.upload(`/api/workflow/faces/${upFace}/drill-report/file`, fd); setUpMsg({ ok: true, r }); } catch (x) { setUpMsg({ ok: false, x }); }
          }} /></label>
          <span className="small muted">{t("reports.drill_formats")}</span>
        </div>
        {upMsg && (upMsg.ok ? <div className="success">{t("reports.uploaded", { n: upMsg.r.summary.drilled })}</div> : <ErrorBox error={upMsg.x} />)}
      </Card>}
    </Page>
  );
}

export function AiPage() {
  const { t } = useTranslation();
  const { data: usage } = useApi<any>("/api/ai/usage", 30000);
  const { data: reqs, reload } = useApi<any[]>("/api/ai/requests", 30000);
  const [sel, setSel] = useState<any>(null);
  return (
    <Page title={t("menu.ai")}>
      {usage && <div className="grid g4" style={{ marginBottom: 12 }}>
        <Stat label={t("ai.provider")} value={`${usage.provider} · ${usage.model}`} />
        <Stat label={t("ai.spent")} value={`$${fmtNum(usage.spent_usd, 4)}`} />
        <Stat label={t("ai.budget_left")} value={`$${fmtNum(usage.left_usd, 2)} / $${usage.budget_usd}`} />
        <Stat label={t("ai.requests_24h")} value={`${usage.requests_24h} / ${usage.max_requests_per_day}`} />
      </div>}
      <div className="notice">{t("ai.only_by_button")}</div>
      <Card title={t("ai.journal")}>
        <Table rows={reqs} onRow={setSel} cols={[
          { key: "ts", title: t("common.time"), render: (r) => r.ts.slice(0, 16).replace("T", " ") }, { key: "username", title: t("common.user") },
          { key: "module", title: t("ai.module"), render: (r) => t(`ai.modules.${r.module}`) }, { key: "entity_id", title: "ID" },
          { key: "model", title: t("ai.model"), render: (r) => `${r.provider} · ${r.model}` }, { key: "tokens", title: t("ai.tokens"), render: (r) => `${r.tokens_in}/${r.tokens_out}` },
          { key: "cost", title: "$", num: true, render: (r) => Number(r.cost).toFixed(4) },
          { key: "cache_hit", title: t("ai.cached"), render: (r) => r.cache_hit ? "✓" : "" }, { key: "demo", title: t("ai.demo"), render: (r) => r.demo ? "✓" : "" },
          { key: "decision", title: t("ai.decision_title"), render: (r) => r.decision ? t(`ai.decision.${r.decision}`) : "" },
        ]} />
      </Card>
      {sel && <Modal wide title={t(`ai.modules.${sel.module}`)} onClose={() => setSel(null)}><AiAnswer req={sel} onDecision={() => { setSel(null); reload(); }} /></Modal>}
    </Page>
  );
}
