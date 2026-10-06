import { useState, Fragment } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import AiPanel from "../components/AiPanel";
import Scene3D from "../components/Scene3D";
import { Action, Badge, Card, ErrorBox, Field, Num, Page, Stat, Table } from "../components/ui";
import { api, download } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { fmtNum } from "../lib/i18n";
import { AnalysisView } from "./FaceDetail";

/** 2D-разрез веера: контур камеры, скважины (заряженная часть), карта распределения энергии. */
export function RingSvg({ res, ring, energy = true, size = 480 }: { res: any; ring: any; energy?: boolean; size?: number }) {
  const sec = res.section;
  const us = sec.map((p: number[]) => p[0]), vs = sec.map((p: number[]) => p[1]);
  const minu = Math.min(...us) - 2, maxu = Math.max(...us) + 2, minv = Math.min(...vs) - 4, maxv = Math.max(...vs) + 2;
  const sc = size / Math.max(maxu - minu, maxv - minv);
  const W = (maxu - minu) * sc, H = (maxv - minv) * sc;
  const X = (u: number) => (u - minu) * sc, Y = (v: number) => H - (v - minv) * sc;
  const [cu, cv] = res.collar;
  const em = res.energy;
  const step = em && em.u.length > 1 ? em.u[1] - em.u[0] : 1;
  return (
    <svg className="svgbox" width="100%" viewBox={`0 0 ${W} ${H}`} style={{ maxWidth: size }}>
      {energy && em?.values?.map((row: (number | null)[], j: number) => row.map((v, i) => {
        if (v === null) return null;
        const k = Math.max(0, Math.min(1, v / (2 * (em.target || 0.6))));
        return <rect key={`${i}-${j}`} x={X(em.u[i] - step / 2)} y={Y(em.v[j] + step / 2)} width={step * sc + 0.5} height={step * sc + 0.5}
          fill={`rgb(${Math.round(255 * k)},${Math.round(200 * (1 - Math.abs(k - 0.5) * 2))},${Math.round(255 * (1 - k))})`} opacity={0.45} />;
      }))}
      <polygon points={sec.map((p: number[]) => `${X(p[0])},${Y(p[1])}`).join(" ")} fill="none" stroke="#111" strokeWidth={1.6} />
      {ring.holes.map((h: any) => {
        const L = h.length || 1, tt = h.uncharged / L;
        return <g key={h.id}>
          <line x1={X(cu)} y1={Y(cv)} x2={X(h.u)} y2={Y(h.v)} stroke={h.status === "blocked" ? "#bbb" : "#666"} strokeDasharray={h.status === "blocked" ? "4 3" : undefined} />
          {h.status !== "blocked" && <line x1={X(cu + (h.u - cu) * tt)} y1={Y(cv + (h.v - cv) * tt)} x2={X(h.u)} y2={Y(h.v)} stroke="#d62728" strokeWidth={2.5} />}
          <text x={X(h.u) + 2} y={Y(h.v) - 2} fontSize={9}>{h.id}: {fmtNum(h.length, 1)}/{fmtNum(h.charge_kg, 0)}</text>
        </g>;
      })}
      <rect x={X(cu - 2.25)} y={Y(cv + 3)} width={4.5 * sc} height={4.5 * sc} fill="#ddd" stroke="#000" />
    </svg>
  );
}

export function StopeList() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const { data } = useApi<any[]>("/api/rings/stopes");
  const [st, setSt] = useState("");
  return (
    <Page title={t("menu.rings")} actions={<select value={st} onChange={(e) => setSt(e.target.value)}><option value="">{t("common.all")}</option>{["planned", "active", "mined"].map((s) => <option key={s} value={s}>{t(`ring.stope_status.${s}`)}</option>)}</select>}>
      <Card>
        <Table rows={(data || []).filter((s) => !st || s.status === st)} onRow={(s) => nav(`/stopes/${s.id}`)} cols={[
          { key: "name", title: t("ring.stope") }, { key: "drive_name", title: t("ring.drive") },
          { key: "levels", title: t("ring.levels"), render: (s) => `${s.level_bottom} … ${s.level_top}` },
          { key: "status", title: t("common.status"), render: (s) => <Badge value={s.status} group="ring.stope_status" /> },
          { key: "designs", title: t("ring.designs"), render: (s) => s.designs.map((d: any) => d.name).join(", ") },
          { key: "face", title: t("workflow.face_status"), render: (s) => s.face ? <Badge value={s.face.status} group="workflow.status" /> : "" },
        ]} />
      </Card>
    </Page>
  );
}

function DesignForm({ stope, onDone }: { stope: any; onDone: (r: any) => void }) {
  const { t } = useTranslation();
  const { data: expl } = useApi<any[]>("/api/explosives");
  const [f, setF] = useState<any>({ hole_diameter: 89, direction: "up", standoff: 0.7, initiation: "edd", ring_interval_ms: 75, spacing_ratio: 1.3, slot_width: 3 });
  const [err, setErr] = useState<unknown>(null);
  return (
    <div>
      <div className="form">
        <Field label={t("explosives.explosive")}><select value={f.explosive_id || ""} onChange={(e) => setF({ ...f, explosive_id: Number(e.target.value) })}><option value="">—</option>{(expl || []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
        <Field label={t("ring.diameter")}><Num value={f.hole_diameter} onChange={(v) => setF({ ...f, hole_diameter: v })} /></Field>
        <Field label={t("ring.direction")}><select value={f.direction} onChange={(e) => setF({ ...f, direction: e.target.value })}>{["up", "down", "mixed"].map((d) => <option key={d} value={d}>{t(`ring.directions.${d}`)}</option>)}</select></Field>
        <Field label={t("ring.standoff")}><Num value={f.standoff} onChange={(v) => setF({ ...f, standoff: v })} /></Field>
        <Field label={t("ring.spacing_ratio")}><Num value={f.spacing_ratio} onChange={(v) => setF({ ...f, spacing_ratio: v })} /></Field>
        <Field label={t("ring.burden_manual")}><Num value={f.burden} onChange={(v) => setF({ ...f, burden: v })} /></Field>
        <Field label={t("ring.slot_width")}><Num value={f.slot_width} onChange={(v) => setF({ ...f, slot_width: v })} /></Field>
        <Field label={t("ring.ring_interval")}><Num value={f.ring_interval_ms} onChange={(v) => setF({ ...f, ring_interval_ms: v })} /></Field>
        <Action className="primary" onClick={async () => { try { onDone(await api.post(`/api/rings/stopes/${stope.id}/design`, f)); } catch (e) { setErr(e); } }}>{t("ring.calculate")}</Action>
      </div>
      <ErrorBox error={err} />
    </div>
  );
}

export function StopeDetail() {
  const { id } = useParams();
  const { t } = useTranslation();
  const nav = useNavigate();
  const { can } = useAuth();
  const { data: s, reload, error } = useApi<any>(`/api/rings/stopes/${id}`, 0, [id]);
  if (!s) return <ErrorBox error={error} />;
  const lastAn = s.analyses?.[0];
  return (
    <Page title={<>{s.name} <Badge value={s.status} group="ring.stope_status" /></>} actions={can("passports.edit") && s.status === "planned" && <Action className="primary" onClick={async () => { await api.post(`/api/rings/stopes/${s.id}/activate`, {}); reload(); }}>{t("ring.activate")}</Action>}>
      <div className="grid g2">
        <Card title={t("ring.stope_params")}>
          <div className="kv">
            <div>{t("ring.levels")}</div><div>{s.level_bottom} … {s.level_top}</div>
            <div>{t("ring.strike")}</div><div>y {s.geometry.y0} … {s.geometry.y1}</div>
            <div>{t("ring.fw_hw")}</div><div>x {s.geometry.x_fw} … {s.geometry.x_hw}</div>
            <div>{t("geology.rock")}</div><div>{s.geology.rock_name} · f={s.geology.f} · ρ={s.geology.density}</div>
            <div>{t("ring.grades")}</div><div>{Object.entries(s.grades || {}).map(([m, g]: any) => `${m} ${g.value} ${g.unit}`).join(", ")}</div>
          </div>
        </Card>
        {can("passports.edit") && <Card title={t("ring.new_design")}><DesignForm stope={s} onDone={(r) => nav(`/rings/${r.id}`)} /></Card>}
      </div>
      <Card title={t("ring.designs")}>
        <Table rows={s.designs} onRow={(d) => nav(`/rings/${d.id}`)} cols={[
          { key: "name", title: t("common.name") }, { key: "status", title: t("common.status"), render: (d) => <Badge value={d.status} group="passport_status" /> },
          { key: "rings", title: t("ring.ind.rings"), num: true, render: (d) => d.indicators.rings },
          { key: "kg_per_t", title: t("ring.ind.kg_per_t"), num: true, render: (d) => fmtNum(d.indicators.kg_per_t, 3) },
          { key: "created_by", title: t("common.user") },
        ]} />
      </Card>
      {lastAn && <Card title={t("ring.results")}><AnalysisView a={lastAn} />{can("ai.use") && <AiPanel module="stope_result" entityId={lastAn.id} />}</Card>}
      {lastAn && <Card title={t("ring.correction")} actions={can("passports.edit") && (lastAn.result.underbreak_zones || []).length > 0 && <Action className="primary small" onClick={async () => { await api.post(`/api/rings/stopes/${s.id}/correction`, {}); reload(); }}>{t("ring.design_correction")}</Action>}>
        {(lastAn.result.underbreak_zones || []).length === 0 && <div className="muted">{t("ring.no_underbreak")}</div>}
        {(s.corrections || []).map((c: any) => <div key={c.id} className="card">
          <div className="row"><b>#{c.id}</b><Badge value={c.status} group="ring.correction_status" />
            <span className={`badge ${c.economics.decision === "recover" ? "ok" : "warn"}`}>{t(`ring.decision.${c.economics.decision}`)}</span>
            {can("passports.edit") && c.status === "proposed" && <><Action className="small" onClick={async () => { await api.post(`/api/rings/corrections/${c.id}/status`, { status: "accepted" }); reload(); }}>{t("ring.accept")}</Action>
              <Action className="small" onClick={async () => { await api.post(`/api/rings/corrections/${c.id}/status`, { status: "rejected" }); reload(); }}>{t("ring.reject")}</Action></>}
            {can("passports.edit") && c.status === "accepted" && <Action className="small" onClick={async () => { await api.post(`/api/rings/corrections/${c.id}/status`, { status: "done" }); reload(); }}>{t("ring.mark_done")}</Action>}
          </div>
          <div className="grid g4" style={{ marginTop: 8 }}>
            <Stat label={t("ring.left_t")} value={fmtNum(c.economics.tonnes, 0)} unit={t("units.t")} />
            <Stat label={t("ring.value")} value={fmtNum(c.economics.value_usd, 0)} unit="USD" />
            <Stat label={t("ring.cost")} value={fmtNum(c.economics.cost_usd, 0)} unit="USD" />
            <Stat label={t("ring.profit")} value={fmtNum(c.economics.profit_usd, 0)} unit="USD" />
          </div>
          <div className="small muted">{t("ring.holes_n", { n: c.design.holes.length })} · {fmtNum(c.economics.drill_m)} {t("units.m")} · {fmtNum(c.economics.explosive_kg)} {t("units.kg")} · {t("ring.downtime")} {fmtNum(c.economics.downtime_h)} {t("units.h")} · {Object.entries(c.economics.metal || {}).map(([m, v]: any) => `${m}: ${fmtNum(v, 2)}`).join(", ")}</div>
          {c.result?.recovered_t !== undefined && <div className="success">{t("ring.recovered", { t: fmtNum(c.result.recovered_t, 0), m3: fmtNum(c.result.remaining_m3, 0) })}</div>}
        </div>)}
      </Card>}
    </Page>
  );
}

export function RingDesign() {
  const { id } = useParams();
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const { data: d, reload, error } = useApi<any>(`/api/rings/designs/${id}`, 0, [id]);
  const [ri, setRi] = useState(0);
  const [lang, setLang] = useState(i18n.language);
  if (!d) return <ErrorBox error={error} />;
  const res = d.design;
  const ring = res.rings[ri];
  const st = d.stope;
  const ringLines = res.rings.flatMap((r: any) => r.holes.map((h: any) => ({
    a: [r.x, res.collar[0], res.collar[1]], b: [r.x, h.u, h.v], color: h.status === "blocked" ? 0x999999 : r.no === ring?.no ? 0xd62728 : 0x2a9d8f })));
  return (
    <Page title={<>{d.name} <Badge value={d.status} group="passport_status" /></>} actions={<>
      {can("passports.approve") && d.status !== "approved" && <Action className="primary" onClick={async () => { await api.post(`/api/rings/designs/${d.id}/status`, { status: "approved" }); reload(); }}>{t("passport_status_action.approved")}</Action>}
      <select value={lang} onChange={(e) => setLang(e.target.value)}>{["ru", "en", "es"].map((l) => <option key={l}>{l}</option>)}</select>
      <Action onClick={() => download(`/api/rings/designs/${d.id}/export/pdf?lang=${lang}`)}>PDF</Action>
      <Action onClick={() => download(`/api/rings/designs/${d.id}/export/dxf`)}>DXF</Action>
      <Action onClick={() => download(`/api/rings/designs/${d.id}/export/csv`)}>CSV Simba</Action>
      {can("ai.use") && <AiPanel module="rings" entityId={d.id} />}
    </>}>
      {(res.warnings || []).map((w: any, i: number) => <div key={i} className={w.level === "error" ? "error" : "notice"}>{String(t(`errors.${w.code}`, w.params))}</div>)}
      <div className="grid g4" style={{ marginBottom: 12 }}>
        <Stat label={t("ring.ind.rings")} value={res.indicators.rings} />
        <Stat label={t("ring.burden")} value={`${res.params.burden} / ${res.params.toe_spacing}`} unit={t("units.m")} />
        <Stat label={t("ring.ind.explosive_kg")} value={fmtNum(res.indicators.explosive_kg, 0)} unit={t("units.kg")} />
        <Stat label={t("ring.ind.kg_per_t")} value={fmtNum(res.indicators.kg_per_t, 3)} />
      </div>
      <div className="grid g2">
        <Card title={<>{t("ring.section")} <select value={ri} onChange={(e) => setRi(Number(e.target.value))}>{res.rings.map((r: any, i: number) => <option key={r.no} value={i}>{t("ring.ring")} {r.no} · x={r.x}</option>)}</select></>}>
          {ring && <RingSvg res={res} ring={ring} energy={ri === 0} />}
          <div className="small muted">{t("ring.energy_note")}</div>
        </Card>
        <Card title={t("ring.view3d")}>
          <Scene3D height={420} stopes={[{ ...st.geometry, level_bottom: st.level_bottom, level_top: st.level_top, name: st.name, status: "active" }]} lines={ringLines} focus={[res.params.x_fw, res.collar[0], res.collar[1]]} />
        </Card>
      </div>
      {ring && <Card title={`${t("ring.ring")} ${ring.no}: ${fmtNum(ring.charge_kg, 0)} ${t("units.kg")} · ${fmtNum(ring.tonnes, 0)} ${t("units.t")} · ${fmtNum(ring.kg_per_t, 3)} ${t("units.kg")}/${t("units.t")}`}>
        <Table rows={ring.holes} cols={[
          { key: "id", title: "№", num: true }, { key: "side", title: t("ring.side"), render: (h) => t(`ring.sides.${h.side}`) },
          { key: "length", title: t("dev_passport.length_m"), num: true }, { key: "angle", title: t("dev_passport.angle_deg"), num: true },
          { key: "uncharged", title: t("ring.uncharged"), num: true }, { key: "charge_length", title: t("workflow.charge_length"), num: true },
          { key: "charge_kg", title: t("dev_passport.charge"), num: true }, { key: "delay_ms", title: t("dev_passport.delay_ms"), num: true },
          { key: "status", title: t("common.status"), render: (h) => t(`ring.hole_status.${h.status || "designed"}`) },
        ]} />
      </Card>}
      <Card title={t("ring.params")}><div className="kv">{Object.entries(res.params).map(([k, v]) => <Fragment key={k}><div>{t(`ring.p.${k}`, { defaultValue: k })}</div><div>{String(v)}</div></Fragment>)}</div></Card>
    </Page>
  );
}
