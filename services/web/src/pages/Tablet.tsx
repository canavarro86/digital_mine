import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";

/** Упрощённая страница для бурильщика и взрывника: крупные кнопки, ввод по шпурам, офлайн-очередь в браузере. */
const QKEY = "dm_tablet_queue";
type Item = { path: string; body: any; ts: string; label: string };
const readQ = (): Item[] => { try { return JSON.parse(localStorage.getItem(QKEY) || "[]"); } catch { return []; } };
const writeQ = (q: Item[]) => { try { localStorage.setItem(QKEY, JSON.stringify(q)); } catch { /* ignore */ } };

export default function Tablet() {
  const { t } = useTranslation();
  const { data: faces, reload } = useApi<any[]>("/api/workflow/faces", 30000);
  const [face, setFace] = useState<any>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [mode, setMode] = useState<"drill" | "charge">("drill");
  const [queue, setQueue] = useState<Item[]>(readQ());
  const [online, setOnline] = useState(navigator.onLine);
  const [msg, setMsg] = useState("");

  const flush = async () => {
    const q = readQ();
    const left: Item[] = [];
    for (const it of q) {
      try { await api.post(it.path, it.body); } catch (e: any) { if (!e?.status || e.status >= 500) left.push(it); }
    }
    writeQ(left); setQueue(left);
    if (q.length && !left.length) { setMsg(t("tablet.sent_all")); reload(); }
  };
  useEffect(() => {
    const on = () => { setOnline(true); flush(); };
    const off = () => setOnline(false);
    window.addEventListener("online", on); window.addEventListener("offline", off);
    const id = setInterval(() => navigator.onLine && readQ().length && flush(), 15000);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); clearInterval(id); };
  }, []);

  const pick = async (f: any) => {
    const d = await api.get(`/api/workflow/faces/${f.id}`);
    setFace(d);
    const src = d.recalc?.result || d.passport?.design;
    if (d.kind === "dev" && src) setRows(src.holes.filter((h: any) => h.type !== "empty").map((h: any) => ({ id: h.id, type: h.type, length: h.length, drilled: true, kg: h.charge_kg, status: "charged", delay_ms: h.delay_ms })));
    else setRows([]);
  };
  const save = async () => {
    if (!face) return;
    const path = mode === "drill" ? `/api/workflow/faces/${face.id}/drill-report` : `/api/workflow/faces/${face.id}/charge-log`;
    const body = mode === "drill" ? { holes: rows.map((r) => ({ id: r.id, length: Number(r.length), drilled: r.drilled })), source: "tablet" }
      : { holes: rows.filter((r) => r.drilled).map((r) => ({ id: r.id, kg: Number(r.kg), status: r.status, delay_ms: r.delay_ms })) };
    const item = { path, body, ts: new Date().toISOString(), label: `${face.name}: ${t(`tablet.${mode}`)}` };
    if (!navigator.onLine) { const q = [...readQ(), item]; writeQ(q); setQueue(q); setMsg(t("tablet.saved_offline")); return; }
    try { await api.post(path, body); setMsg(t("tablet.sent")); setFace(null); reload(); }
    catch (e: any) { if (!e?.status || e.status >= 500) { const q = [...readQ(), item]; writeQ(q); setQueue(q); setMsg(t("tablet.saved_offline")); } else setMsg(e.code); }
  };
  const upd = (i: number, k: string, v: any) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  return (
    <div className="tablet">
      <div className="row"><h1>{t("menu.tablet")}</h1><Badge value={online ? "ok" : "error"} /> {online ? t("tablet.online") : t("tablet.offline")}
        {queue.length > 0 && <span className="badge warn">{t("tablet.queue", { n: queue.length })} <button className="small" onClick={flush}>{t("tablet.send_now")}</button></span>}</div>
      {msg && <div className="success">{msg}</div>}
      {!face && <div className="grid g3" style={{ marginTop: 12 }}>
        {(faces || []).filter((f) => f.kind === "dev" && ["ready", "drilling", "accepted"].includes(f.status)).map((f) =>
          <button key={f.id} onClick={() => { setMode(f.status === "accepted" ? "charge" : "drill"); pick(f); }}>{f.name}<br /><small>{t(`workflow.status.${f.status}`)}</small></button>)}
      </div>}
      {face && <div className="card" style={{ marginTop: 12 }}>
        <div className="row"><h2>{face.name}</h2><button onClick={() => setMode("drill")} className={mode === "drill" ? "primary" : ""}>{t("tablet.drill")}</button>
          <button onClick={() => setMode("charge")} className={mode === "charge" ? "primary" : ""}>{t("tablet.charge")}</button><button onClick={() => setFace(null)}>✕</button></div>
        <div className="tbl-wrap"><table className="t"><thead><tr><th>№</th><th>{t("dev_passport.type")}</th>
          {mode === "drill" ? <><th>{t("dev_passport.length_m")}</th><th>{t("workflow.drilled")}</th></> : <><th>{t("units.kg")}</th><th>{t("common.status")}</th></>}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={r.id}><td><b>{r.id}</b></td><td>{t(`dev_passport.hole_types.${r.type}`)}</td>
            {mode === "drill" ? <><td><input type="number" step="0.01" value={r.length} onChange={(e) => upd(i, "length", e.target.value)} /></td>
              <td><button className={r.drilled ? "primary" : "danger"} onClick={() => upd(i, "drilled", !r.drilled)}>{r.drilled ? "✓" : "✗"}</button></td></>
              : <><td><input type="number" step="0.1" value={r.kg} onChange={(e) => upd(i, "kg", e.target.value)} /></td>
                <td><select value={r.status} onChange={(e) => upd(i, "status", e.target.value)}>{["charged", "not_charged", "misfire"].map((s) => <option key={s} value={s}>{t(`workflow.charge_status.${s}`)}</option>)}</select></td></>}
          </tr>)}</tbody></table></div>
        <button className="primary" style={{ marginTop: 12, width: "100%" }} onClick={save}>{t("tablet.save")}</button>
      </div>}
    </div>
  );
}
