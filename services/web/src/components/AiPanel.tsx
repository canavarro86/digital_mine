import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { errText } from "../lib/i18n";
import { Modal } from "./ui";

export function AiAnswer({ req, onDecision }: { req: any; onDecision?: (d: any) => void }) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const r = req.response || {};
  const [err, setErr] = useState<unknown>(null);
  const list = (x: any) => (Array.isArray(x) ? x : x ? [x] : []);
  return (
    <div>
      {req.cache_hit && <div className="notice">{t("ai.from_cache")}</div>}
      {req.demo && <div className="notice">{t("ai.demo_mode")}</div>}
      <h3>{t("ai.problems")}</h3><ul>{list(r.problems).map((p: any, i: number) => <li key={i}>{typeof p === "string" ? p : JSON.stringify(p)}</li>)}</ul>
      <h3>{t("ai.causes")}</h3><ul>{list(r.causes).map((p: any, i: number) => <li key={i}>{typeof p === "string" ? p : JSON.stringify(p)}</li>)}</ul>
      <h3>{t("ai.changes")}</h3>
      <table className="t"><thead><tr><th>{t("ai.param")}</th><th>{t("ai.was")}</th><th>{t("ai.now")}</th><th>{t("ai.why")}</th></tr></thead>
        <tbody>{list(r.changes).map((c: any, i: number) => <tr key={i}><td>{c.param}</td><td>{String(c.was ?? "")}</td><td><b>{String(c.now ?? "")}</b></td><td className="small">{c.why}</td></tr>)}</tbody></table>
      <h3>{t("ai.effect")}</h3><p>{typeof r.effect === "string" ? r.effect : JSON.stringify(r.effect)}</p>
      <div className="small muted">{req.provider} · {req.model} · {t("ai.tokens")}: {req.tokens_in}/{req.tokens_out} · ${Number(req.cost).toFixed(4)}</div>
      {onDecision && !req.decision && <div className="row" style={{ marginTop: 10 }}>
        {["dev_passport", "dev_recalc"].includes(req.module) && <button className="primary" onClick={async () => {
          try { const d = await api.post(`/api/ai/requests/${req.id}/decision`, { decision: "applied" }); onDecision(d); nav(`/passports/${d.passport_id}`); } catch (e) { setErr(e); }
        }}>{t("ai.apply_copy")}</button>}
        <button onClick={async () => { await api.post(`/api/ai/requests/${req.id}/decision`, { decision: "rejected" }); onDecision({ rejected: true }); }}>{t("ai.reject")}</button>
      </div>}
      {req.decision && <div className="badge info">{t(`ai.decision.${req.decision}`)}</div>}
      {!!err && <div className="error">{errText(err)}</div>}
    </div>
  );
}

/** Кнопка «Отправить на анализ ИИ»: предпросмотр (размер, $) → «Отправить» / «Отмена» → ответ. */
export default function AiPanel({ module, entityId }: { module: string; entityId: string | number }) {
  const { t, i18n } = useTranslation();
  const [pv, setPv] = useState<any>(null);
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const open = async () => {
    setErr(null); setRes(null);
    try { setPv(await api.post("/api/ai/preview", { module, entity_id: entityId, lang: i18n.language })); } catch (e) { setErr(e); setPv({}); }
  };
  return (
    <span>
      <button onClick={open}>🤖 {t("ai.send_button")}</button>
      {pv && <Modal title={t("ai.title")} onClose={() => setPv(null)} wide footer={!res && pv.prompt && <>
        <button onClick={() => setPv(null)}>{t("common.cancel")}</button>
        <button className="primary" disabled={busy || !!pv.blocked} onClick={async () => {
          setBusy(true); setErr(null);
          try { setRes(await api.post("/api/ai/send", { module, entity_id: entityId, lang: i18n.language })); } catch (e) { setErr(e); } finally { setBusy(false); }
        }}>{busy ? "…" : t("ai.send")}</button></>}>
        {!!err && <div className="error">{errText(err)}</div>}
        {!res && pv.prompt && <div>
          <div className="row">
            <span className="badge info">{pv.provider} · {pv.model}</span>
            <span className="badge">{t("ai.size")}: {pv.chars} {t("ai.chars")} ≈ {pv.tokens_in_est} {t("ai.tokens")}</span>
            <span className="badge warn">{t("ai.cost_est")}: ${pv.cost_est_usd}</span>
            {pv.cached && <span className="badge ok">{t("ai.cached")}</span>}
            <span className="badge">{t("ai.budget_left")}: ${pv.usage.left_usd} / ${pv.usage.budget_usd}</span>
          </div>
          {pv.blocked && <div className="error">{t(`errors.ai_${pv.blocked}`)}</div>}
          <h3>{t("ai.preview")}</h3><pre className="code">{pv.prompt}</pre>
        </div>}
        {res && <AiAnswer req={res} onDecision={() => setPv(null)} />}
      </Modal>}
    </span>
  );
}
