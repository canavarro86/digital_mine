import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Action, Badge, Card, ErrorBox, Modal, Page, Table } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";

function Reassign({ alert, onDone }: { alert: any; onDone: () => void }) {
  const { t } = useTranslation();
  const [err, setErr] = useState<unknown>(null);
  return (
    <div>
      <p>{alert.text}</p>
      <h3>{t("alerts.ready_faces")}</h3>
      <table className="t">
        <thead><tr><th>{t("workflow.face")}</th><th>{t("alerts.priority")}</th><th>{t("alerts.distance")}</th><th>{t("alerts.drill_hours")}</th><th>{t("alerts.blast_col")}</th><th /></tr></thead>
        <tbody>
          {(alert.params.candidates || []).map((c: any) => (
            <tr key={c.face_id}><td>{c.name}</td><td>{c.priority}</td><td>{c.distance_m ?? "—"}</td><td>{c.hours}</td>
              <td>{c.carry_over ? <span className="badge warn">{t("alerts.carry_over")}</span> : c.blast_at ? <span className="badge ok">{t("alerts.fits_blast", { time: c.blast_at })}</span> : "—"}</td>
              <td><button className="primary small" onClick={async () => {
                try {
                  await api.post("/api/dispatch/reassign", { assignment_id: alert.params.assignment_id, face_id: c.face_id, alert_id: alert.id, reason: "alert" });
                  onDone();
                } catch (e) { setErr(e); }
              }}>{t("alerts.reassign")}</button></td></tr>
          ))}
        </tbody>
      </table>
      <ErrorBox error={err} />
    </div>
  );
}

export default function Alerts() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [status, setStatus] = useState("open");
  const { data, reload } = useApi<any[]>(`/api/alerts?status=${status}`, 15000, [status]);
  const [sel, setSel] = useState<any>(null);
  const act = can("alerts.dispatch.act");
  return (
    <Page title={t("menu.alerts")} actions={
      <select value={status} onChange={(e) => setStatus(e.target.value)}>
        {["open", "ack", "resolved", ""].map((s) => <option key={s} value={s}>{s ? t(`alerts.status.${s}`) : t("common.all")}</option>)}
      </select>}>
      <Card>
        <Table rows={data} empty={t("alerts.none")} cols={[
          { key: "ts_mine", title: t("common.time_site") },
          { key: "ts_user", title: t("common.time_me") },
          { key: "audience", title: t("alerts.audience"), render: (a) => t(`alerts.aud.${a.audience}`) },
          { key: "severity", title: "", render: (a) => <Badge value={a.severity} /> },
          { key: "title", title: t("alerts.alert"), render: (a) => <b>{a.title}</b> },
          { key: "text", title: t("common.details") },
          { key: "status", title: t("common.status"), render: (a) => <Badge value={a.status} group="alerts.status" /> },
          { key: "act", title: "", render: (a) => a.status !== "resolved" && (a.audience !== "dispatcher" || act) ? (
            <span className="row">
              {a.rule === "rig_free_early" && act && <button className="primary small" onClick={() => setSel(a)}>{t("alerts.reassign")}</button>}
              {a.rule === "machine_idle" && act && <Action className="small" onClick={async () => {
                const reason = window.prompt(t("alerts.idle_reason")) || "";
                if (reason) { await api.post(`/api/alerts/${a.id}/status`, { status: "ack", reason }); reload(); }
              }}>{t("alerts.idle_reason_btn")}</Action>}
              {a.status === "open" && <Action className="small" onClick={async () => { await api.post(`/api/alerts/${a.id}/status`, { status: "ack" }); reload(); }}>{t("alerts.ack")}</Action>}
              <Action className="small" onClick={async () => { await api.post(`/api/alerts/${a.id}/status`, { status: "resolved" }); reload(); }}>{t("alerts.resolve")}</Action>
            </span>) : null },
        ]} />
      </Card>
      {sel && <Modal title={sel.title} onClose={() => setSel(null)}><Reassign alert={sel} onDone={() => { setSel(null); reload(); }} /></Modal>}
    </Page>
  );
}
