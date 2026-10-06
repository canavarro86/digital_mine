import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import AiPanel from "../components/AiPanel";
import FaceSvg, { HOLE_COLORS } from "../components/FaceSvg";
import { Action, Badge, Card, ErrorBox, Field, Modal, Num, Page, Table } from "../components/ui";
import { api, download } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { fmtNum } from "../lib/i18n";

export function NewPassport({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const { data: ws } = useApi<any[]>("/api/workings");
  const [wid, setWid] = useState<number | null>(null);
  const { data: sug } = useApi<any>(wid ? `/api/passports/suggest?working_id=${wid}` : null, 0, [wid]);
  const [tp, setTp] = useState<number | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { if (sug?.candidates?.length) setTp(sug.candidates[0].id); }, [sug]);
  return (
    <Modal title={t("dev_passport.new")} onClose={onClose} footer={<>
      <button onClick={onClose}>{t("common.cancel")}</button>
      <button className="primary" disabled={!wid} onClick={async () => {
        try { const p = await api.post("/api/passports/dev", { working_id: wid, typical_id: tp }); nav(`/passports/${p.id}`); } catch (e) { setErr(e); }
      }}>{t("common.create")}</button></>}>
      <div className="form">
        <Field label={t("workings.working")}>
          <select value={wid || ""} onChange={(e) => setWid(Number(e.target.value))}>
            <option value="">—</option>
            {(ws || []).filter((w) => w.type !== "ramp").map((w) => <option key={w.id} value={w.id}>{w.name} · {t(`workings.status.${w.status}`)}</option>)}
          </select>
        </Field>
        {sug && <Field label={t("dev_passport.typical_suggested")}>
          <select value={tp || ""} onChange={(e) => setTp(Number(e.target.value) || null)}>
            <option value="">{t("dev_passport.no_typical")}</option>
            {sug.candidates.map((c: any) => <option key={c.id} value={c.id}>{c.number} · {c.name} ({c.score})</option>)}
          </select>
        </Field>}
      </div>
      {sug && <div className="small muted" style={{ marginTop: 8 }}>{t("dev_passport.geology_at")}: {sug.geology.rock_name} · f={sug.geology.f} · {t(`geology.water_levels.${sug.geology.water}`)} · {t("geology.fracture_cat")} {sug.geology.fracture_cat} · {t("geology.priority")}: {t(`geology.targets.${sug.geology.priority}`)}</div>}
      <ErrorBox error={err} />
    </Modal>
  );
}

export function PassportList() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const { can } = useAuth();
  const { data } = useApi<any[]>("/api/passports/dev");
  const [modal, setModal] = useState(false);
  return (
    <Page title={t("menu.passports")} actions={can("passports.edit") && <button className="primary" onClick={() => setModal(true)}>+ {t("dev_passport.new")}</button>}>
      <Card>
        <Table rows={data} onRow={(p) => nav(`/passports/${p.id}`)} cols={[
          { key: "number", title: "№" }, { key: "working_name", title: t("workings.working") }, { key: "name", title: t("common.name") },
          { key: "status", title: t("common.status"), render: (p) => <Badge value={p.status} group="passport_status" /> },
          { key: "version", title: t("common.version"), num: true },
          { key: "holes", title: t("dev_passport.holes"), num: true, render: (p) => p.indicators?.holes_total },
          { key: "q", title: t("dev_passport.q"), num: true, render: (p) => fmtNum(p.indicators?.q_actual, 2) },
          { key: "kish", title: t("dev_passport.kish"), num: true, render: (p) => fmtNum(p.indicators?.kish, 2) },
          { key: "parent_id", title: t("dev_passport.parent"), render: (p) => p.parent_id ? `#${p.parent_id}` : "" },
        ]} />
      </Card>
      {modal && <NewPassport onClose={() => setModal(false)} />}
    </Page>
  );
}

function InputForm({ p, onCalc, disabled }: { p: any; onCalc: (inp: any) => Promise<void>; disabled: boolean }) {
  const { t } = useTranslation();
  const { data: expl } = useApi<any[]>("/api/explosives");
  const { data: cuts } = useApi<any[]>("/api/passports/cuts");
  const { data: init } = useApi<any[]>("/api/initiation");
  const [inp, setInp] = useState<any>(() => ({
    section: { ...p.input.section }, hole_depth: p.input.hole_depth, hole_diameter: p.input.hole_diameter, empty_diameter: p.input.empty_diameter,
    cut: { ...p.input.cut }, initiation: p.input.initiation, contour_blasting: p.design.params.contour_blasting, lookout_deg: p.input.lookout_deg ?? 3,
    explosive_id: p.input.explosive?.id, contour_explosive_id: p.input.contour_explosive?.id,
    rock_override: { f: p.input.rock?.f, fracture_cat: p.input.rock?.fracture_cat, water: p.input.rock?.water },
  }));
  const s = (k: string, v: any) => setInp({ ...inp, [k]: v });
  const sec = (k: string, v: any) => setInp({ ...inp, section: { ...inp.section, [k]: v } });
  return (
    <div>
      <div className="form">
        <Field label={t("dev_passport.section")}>
          <select value={inp.section.shape} onChange={(e) => sec("shape", e.target.value)} disabled={disabled}>
            {["arch", "rect", "trapezoid", "horseshoe"].map((x) => <option key={x} value={x}>{t(`dev_passport.shapes.${x}`)}</option>)}
          </select>
        </Field>
        <Field label={t("dev_passport.width")}><Num value={inp.section.width} onChange={(v) => sec("width", v)} disabled={disabled} /></Field>
        <Field label={t("dev_passport.height")}><Num value={inp.section.height} onChange={(v) => sec("height", v)} disabled={disabled} /></Field>
        {inp.section.shape === "arch" && <Field label={t("dev_passport.arch_height")}><Num value={inp.section.arch_height} onChange={(v) => sec("arch_height", v)} disabled={disabled} /></Field>}
        {inp.section.shape === "trapezoid" && <Field label={t("dev_passport.top_width")}><Num value={inp.section.top_width} onChange={(v) => sec("top_width", v)} disabled={disabled} /></Field>}
        <Field label={t("geology.f")}><Num value={inp.rock_override.f} onChange={(v) => s("rock_override", { ...inp.rock_override, f: v })} disabled={disabled} /></Field>
        <Field label={t("geology.fracture_cat")}><Num value={inp.rock_override.fracture_cat} step="1" onChange={(v) => s("rock_override", { ...inp.rock_override, fracture_cat: v })} disabled={disabled} /></Field>
        <Field label={t("geology.water")}>
          <select value={inp.rock_override.water} onChange={(e) => s("rock_override", { ...inp.rock_override, water: e.target.value })} disabled={disabled}>
            {["dry", "damp", "dripping", "flowing", "inflow"].map((w) => <option key={w} value={w}>{t(`geology.water_levels.${w}`)}</option>)}
          </select>
        </Field>
        <Field label={t("explosives.explosive")}>
          <select value={inp.explosive_id || ""} onChange={(e) => s("explosive_id", Number(e.target.value))} disabled={disabled}>{(expl || []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
        </Field>
        <Field label={t("dev_passport.contour_explosive")}>
          <select value={inp.contour_explosive_id || ""} onChange={(e) => s("contour_explosive_id", Number(e.target.value))} disabled={disabled}>{(expl || []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
        </Field>
        <Field label={t("dev_passport.depth")}><Num value={inp.hole_depth} onChange={(v) => s("hole_depth", v)} disabled={disabled} /></Field>
        <Field label={t("dev_passport.diameter_work")}><Num value={inp.hole_diameter} onChange={(v) => s("hole_diameter", v)} disabled={disabled} /></Field>
        <Field label={t("dev_passport.diameter_empty")}><Num value={inp.empty_diameter} onChange={(v) => s("empty_diameter", v)} disabled={disabled} /></Field>
        <Field label={t("dev_passport.cut")}>
          <select value={inp.cut.type} onChange={(e) => s("cut", { ...inp.cut, type: e.target.value })} disabled={disabled}>
            {["prismatic", "slot", "spiral", "wedge", "pyramid"].map((x) => <option key={x} value={x}>{t(`dev_passport.cut_types.${x}`)}</option>)}
          </select>
        </Field>
        <Field label={t("dev_passport.cut_library")}>
          <select value="" onChange={(e) => { const c = (cuts || []).find((x) => x.id === Number(e.target.value)); if (c) setInp({ ...inp, cut: { type: c.type, ...c.params }, empty_diameter: c.params.empty_diameter ?? inp.empty_diameter }); }} disabled={disabled}>
            <option value="">—</option>{(cuts || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label={t("dev_passport.n_empty")}><Num value={inp.cut.n_empty} step="1" onChange={(v) => s("cut", { ...inp.cut, n_empty: v })} disabled={disabled} /></Field>
        <Field label={t("dev_passport.initiation")}>
          <select value={inp.initiation} onChange={(e) => s("initiation", e.target.value)} disabled={disabled}>
            <option value="edd">{t("explosives.kinds.edd")}</option><option value="nonel">{t("explosives.kinds.nonel")}</option>
          </select>
        </Field>
        <Field label={t("dev_passport.contour_blasting")}><input type="checkbox" checked={!!inp.contour_blasting} onChange={(e) => s("contour_blasting", e.target.checked)} disabled={disabled} /></Field>
        <Field label={t("dev_passport.lookout")}><Num value={inp.lookout_deg} onChange={(v) => s("lookout_deg", v)} disabled={disabled} /></Field>
        <Action className="primary" disabled={disabled} onClick={() => onCalc(inp)}>{t("dev_passport.calculate")}</Action>
      </div>
      {init && <div className="small muted" style={{ marginTop: 6 }}>{t("dev_passport.devices")}: {init.map((d) => d.name).join(", ")}</div>}
    </div>
  );
}

function SectionAA({ p }: { p: any }) {
  const { t } = useTranslation();
  const depth = Number(p.input.hole_depth) + 0.6;
  const H = p.params.height + 0.4;
  const W = 520, Hpx = 190, sx = (W - 40) / depth, sy = (Hpx - 30) / H;
  const seen = new Set<string>();
  return (
    <svg className="svgbox" width="100%" viewBox={`0 0 ${W} ${Hpx}`} style={{ maxWidth: W }}>
      <rect x={20} y={10} width={(depth - 0.6) * sx} height={p.params.height * sy} fill="#f6f7f9" stroke="#111" />
      {p.holes.filter((h: any) => { const k = `${h.type}${Math.round(h.y * 2)}`; if (seen.has(k)) return false; seen.add(k); return true; }).map((h: any) => {
        const ang = ((h.angle || 0) * Math.PI) / 180, sign = h.y > p.params.height / 2 ? 1 : -1, L = h.length || depth;
        const y0 = 10 + (p.params.height - h.y) * sy;
        return <g key={h.id}><line x1={20} y1={y0} x2={20 + L * Math.cos(ang) * sx} y2={y0 - sign * L * Math.sin(ang) * sy} stroke={HOLE_COLORS[h.type]} strokeWidth={1.4} />
          {h.charge_length > 0 && <line x1={20 + (L - h.charge_length) * sx} y1={y0 - sign * (L - h.charge_length) * Math.sin(ang) * sy} x2={20 + L * Math.cos(ang) * sx} y2={y0 - sign * L * Math.sin(ang) * sy} stroke={HOLE_COLORS[h.type]} strokeWidth={4} opacity={0.5} />}</g>;
      })}
      <text x={W / 2} y={Hpx - 6} fontSize={10} textAnchor="middle">{t("dev_passport.section_aa")}: L = {p.input.hole_depth} {t("units.m")}</text>
    </svg>
  );
}

export function PassportEditor() {
  const { id } = useParams();
  const { t, i18n } = useTranslation();
  const nav = useNavigate();
  const { can } = useAuth();
  const { data: p, reload, setData, error } = useApi<any>(`/api/passports/dev/${id}`, 0, [id]);
  const [sel, setSel] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [lang, setLang] = useState(i18n.language);
  const [addType, setAddType] = useState("stoping");
  const [tpModal, setTpModal] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const edit = can("passports.edit");
  if (!p) return <ErrorBox error={error} />;
  const d = p.design;
  const ind = p.indicators;

  const evalHoles = (holes: any[]) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      try {
        const res = await api.post(`/api/passports/dev/${p.id}/evaluate`, { holes });
        setData({ ...p, design: res, indicators: res.indicators });
      } catch (e) { setErr(e); }
    }, 250);
  };
  const setHoles = (holes: any[], recalc = true) => {
    setData({ ...p, design: { ...d, holes } });
    setDirty(true);
    if (recalc) evalHoles(holes);
  };
  const selHole = d.holes.find((h: any) => h.id === sel);
  return (
    <Page title={<>{t("dev_passport.title")} {p.number} <Badge value={p.status} group="passport_status" /></>} actions={<>
      {dirty && edit && <Action className="primary" onClick={async () => { await api.put(`/api/passports/dev/${p.id}`, { holes: d.holes }); setDirty(false); reload(); }}>{t("common.save")}</Action>}
      {edit && p.status === "draft" && <Action onClick={async () => { await api.post(`/api/passports/dev/${p.id}/status`, { status: "review" }); reload(); }}>{t("passport_status_action.review")}</Action>}
      {can("passports.approve") && p.status === "review" && <Action className="primary" onClick={async () => { await api.post(`/api/passports/dev/${p.id}/status`, { status: "approved" }); reload(); }}>{t("passport_status_action.approved")}</Action>}
      {edit && p.status === "approved" && <Action onClick={async () => { await api.post(`/api/passports/dev/${p.id}/status`, { status: "archived" }); reload(); }}>{t("passport_status_action.archived")}</Action>}
      {edit && <Action onClick={async () => { const c = await api.post(`/api/passports/dev/${p.id}/copy`, {}); nav(`/passports/${c.id}`); }}>{t("common.copy")}</Action>}
      {edit && <button onClick={() => setTpModal(true)}>{t("dev_passport.save_as_typical")}</button>}
      <select value={lang} onChange={(e) => setLang(e.target.value)}>{["ru", "en", "es"].map((l) => <option key={l}>{l}</option>)}</select>
      <Action onClick={() => download(`/api/passports/dev/${p.id}/export/pdf?lang=${lang}`)}>PDF</Action>
      <Action onClick={() => download(`/api/passports/dev/${p.id}/export/dxf`)}>DXF</Action>
      <Action onClick={() => download(`/api/passports/dev/${p.id}/export/csv`)}>CSV</Action>
      {can("ai.use") && <AiPanel module="dev_passport" entityId={p.id} />}
    </>}>
      <div className="small muted" style={{ marginBottom: 8 }}>{p.working_name && <Link to={`/workings`}>{p.working_name}</Link>} · {t("geology.rock")}: {p.input.rock?.rock_name || "—"} ({t(`geology.targets.${p.input.rock?.source || "none"}`)})</div>
      <ErrorBox error={err} />
      {(d.warnings || []).map((w: any, i: number) => <div key={i} className={w.level === "error" ? "error" : "notice"}>{String(t(`errors.${w.code}`, w.params))}</div>)}
      <Card title={t("dev_passport.input")}><InputForm p={p} disabled={!edit} onCalc={async (inp) => {
        try { setErr(null); await api.put(`/api/passports/dev/${p.id}`, { input: inp }); setDirty(false); await reload(); } catch (e) { setErr(e); }
      }} /></Card>
      <div className="grid g2">
        <Card title={t("dev_passport.face_view")} actions={edit && <span className="row">
          <select value={addType} onChange={(e) => setAddType(e.target.value)}>{Object.keys(HOLE_COLORS).map((k) => <option key={k} value={k}>{t(`dev_passport.hole_types.${k}`)}</option>)}</select>
          <button className="small" onClick={() => { const nid = Math.max(...d.holes.map((h: any) => h.id)) + 1; setHoles([...d.holes, { id: nid, x: 0, y: d.params.cut_height + 1.2, type: addType }]); setSel(nid); }}>+ {t("dev_passport.add_hole")}</button>
          {selHole && <>
            <select value={selHole.type} onChange={(e) => setHoles(d.holes.map((h: any) => h.id === sel ? { ...h, type: e.target.value } : h))}>{Object.keys(HOLE_COLORS).map((k) => <option key={k} value={k}>{t(`dev_passport.hole_types.${k}`)}</option>)}</select>
            <button className="small danger" onClick={() => { setHoles(d.holes.filter((h: any) => h.id !== sel)); setSel(null); }}>{t("dev_passport.delete_hole")} №{sel}</button>
          </>}
        </span>}>
          <FaceSvg result={d} editable={edit} selected={sel} onSelect={setSel}
            onMove={(hid, x, y, done) => setHoles(d.holes.map((h: any) => h.id === hid ? { ...h, x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000 } : h), done)} />
          {selHole && <div className="small">№{selHole.id} · {t(`dev_passport.hole_types.${selHole.type}`)} · x={fmtNum(selHole.x, 2)} y={fmtNum(selHole.y, 2)} · {t("dev_passport.nn")}: {fmtNum(selHole.nn_dist, 2)} {selHole.flag && <Badge value={t(`dev_passport.flags.${selHole.flag}`)} />}</div>}
        </Card>
        <div>
          <Card title={t("dev_passport.indicators")}>
            <div className="kv">
              <div>{t("dev_passport.area")}</div><div>{fmtNum(ind.area, 2)} {t("units.m2")}</div>
              <div>{t("dev_passport.depth")}</div><div>{fmtNum(ind.depth, 2)} {t("units.m")}</div>
              <div>{t("dev_passport.kish")}</div><div>{fmtNum(ind.kish, 2)}</div>
              <div>{t("dev_passport.advance")}</div><div>{fmtNum(ind.advance, 2)} {t("units.m")}</div>
              <div>{t("dev_passport.volume")}</div><div>{fmtNum(ind.volume)} {t("units.m3")} · {fmtNum(ind.tonnes, 0)} {t("units.t")}</div>
              <div>{t("dev_passport.q")}</div><div>{fmtNum(ind.q_actual, 2)} {t("units.kg_m3")} ({t("dev_passport.pokrovsky")}: {fmtNum(ind.q_pokrovsky, 2)})</div>
              <div>{t("dev_passport.explosive_cycle")}</div><div>{fmtNum(ind.explosive_kg)} {t("units.kg")} · {fmtNum(ind.kg_per_m)} {t("units.kg")}/{t("units.m")}</div>
              <div>{t("dev_passport.holes")}</div><div>{ind.holes_total} ({t("dev_passport.pokrovsky")}: {ind.holes_pokrovsky}) · {Object.entries(ind.holes_by_type || {}).filter(([, n]) => n).map(([k, n]) => `${t(`dev_passport.hole_types.${k}`)} ${n}`).join(", ")}</div>
              <div>{t("dev_passport.drill_m")}</div><div>{fmtNum(ind.drill_m)} {t("units.m")} · {fmtNum(ind.drill_time_h, 1)} {t("units.h")}</div>
              <div>{t("dev_passport.detonators")}</div><div>{ind.detonators} · {t("dev_passport.max_delay")} {ind.max_delay_ms} {t("units.ms")}</div>
              <div>{t("dev_passport.cost")}</div><div>{fmtNum(ind.cost, 0)} USD</div>
              <div>{t("dev_passport.burdens")}</div><div className="small">B={fmtNum(d.params.B_stoping, 2)} · E={fmtNum(d.params.E_stoping, 2)} · B<sub>п</sub>={fmtNum(d.params.B_lifter, 2)} · B<sub>к</sub>={fmtNum(d.params.B_contour, 2)} · E<sub>к</sub>={fmtNum(d.params.E_contour, 2)} · E/B={fmtNum(d.params.contour_ratio, 2)}</div>
              <div>{t("dev_passport.cut")}</div><div className="small">φ={fmtNum(d.params.phi, 3)} · H<sub>max</sub>={fmtNum(d.params.cut_max_depth, 2)} · {(d.params.cut_sections || []).map((s: any) => `${s.n}: B=${s.B} W=${s.W}`).join("; ")}</div>
            </div>
          </Card>
          <Card title={t("dev_passport.section_aa")}><SectionAA p={d} /></Card>
          <Card title={t("dev_passport.signatures")}>
            <div className="kv">
              <div>{t("dev_passport.made")}</div><div>{p.signatures?.made || "—"}</div>
              <div>{t("dev_passport.checked")}</div><div>{p.signatures?.checked || "—"}</div>
              <div>{t("dev_passport.approved")}</div><div>{p.signatures?.approved || "—"} {p.signatures?.approved_at && <span className="muted small">{p.signatures.approved_at}</span>}</div>
            </div>
          </Card>
        </div>
      </div>
      <Card title={t("dev_passport.holes_table")}>
        <Table rows={d.holes} onRow={(h) => setSel(h.id)} cols={[
          { key: "id", title: "№", num: true },
          { key: "type", title: t("dev_passport.type"), render: (h) => <span><i style={{ display: "inline-block", width: 9, height: 9, borderRadius: 5, background: HOLE_COLORS[h.type], border: "1px solid #333", marginRight: 4 }} />{t(`dev_passport.hole_types.${h.type}`)}</span> },
          { key: "diameter", title: t("dev_passport.diameter_mm"), num: true },
          { key: "length", title: t("dev_passport.length_m"), num: true },
          { key: "angle", title: t("dev_passport.angle_deg"), num: true },
          { key: "charge_kg", title: t("dev_passport.charge"), num: true, render: (h) => h.type === "empty" ? "—" : `${fmtNum(h.charge_kg, 2)}${h.cartridges ? ` (${h.cartridges} ${t("dev_passport.cart")})` : ""}` },
          { key: "stemming", title: t("dev_passport.stemming_m"), num: true },
          { key: "delay_ms", title: t("dev_passport.delay_ms"), num: true, render: (h) => h.type === "empty" ? "" : `${h.delay_ms ?? ""}${h.delay_no ? ` (№${h.delay_no})` : ""}` },
          { key: "flag", title: "", render: (h) => h.flag ? <Badge value={t(`dev_passport.flags.${h.flag}`)} /> : null },
        ]} />
      </Card>
      {tpModal && <TypicalFromDev p={p} onClose={() => setTpModal(false)} />}
    </Page>
  );
}

function TypicalFromDev({ p, onClose }: { p: any; onClose: () => void }) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const [f, setF] = useState<any>({ number: `ТП-${p.id}`, name: p.name, working_type: "fwd", f_min: (p.input.rock?.f || 10) - 2, f_max: (p.input.rock?.f || 10) + 2, water: ["dry", "damp"] });
  const [err, setErr] = useState<unknown>(null);
  return (
    <Modal title={t("dev_passport.save_as_typical")} onClose={onClose} footer={<button className="primary" onClick={async () => {
      try { const r = await api.post("/api/passports/typical", { ...f, from_dev_id: p.id }); nav(`/typical/${r.id}`); } catch (e) { setErr(e); }
    }}>{t("common.save")}</button>}>
      <div className="form">
        <Field label="№"><input value={f.number} onChange={(e) => setF({ ...f, number: e.target.value })} /></Field>
        <Field label={t("common.name")}><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label={t("workings.type")}><select value={f.working_type} onChange={(e) => setF({ ...f, working_type: e.target.value })}>{["ramp", "access", "fwd", "xc", "other"].map((x) => <option key={x} value={x}>{t(`workings.types.${x}`)}</option>)}</select></Field>
        <Field label="f min"><Num value={f.f_min} onChange={(v) => setF({ ...f, f_min: v })} /></Field>
        <Field label="f max"><Num value={f.f_max} onChange={(v) => setF({ ...f, f_max: v })} /></Field>
      </div>
      <ErrorBox error={err} />
    </Modal>
  );
}
