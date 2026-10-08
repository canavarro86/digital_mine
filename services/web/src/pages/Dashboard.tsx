import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Badge, Card, Page, Stat, Table } from "../components/ui";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { fmtNum } from "../lib/i18n";
import { BoardTable } from "./Board";

export default function Dashboard() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const { data: faces } = useApi<any[]>(can("dispatch.view", "workings.view") ? "/api/workflow/faces" : null, 15000);
  const { data: rep } = useApi<any>(can("reports.view") ? "/api/reports/period?period=day" : null, 30000);
  const { data: alerts } = useApi<any[]>("/api/alerts?status=open&limit=8", 20000);
  const byStatus: Record<string, number> = {};
  (faces || []).forEach((f) => { byStatus[f.status] = (byStatus[f.status] || 0) + 1; });
  return (
    <Page title={t("menu.dashboard")}>
      {rep && <div className="grid g4" style={{ marginBottom: 14 }}>
        <Stat label={t("dash.advance_day")} value={fmtNum(rep.development.advance_m)} unit={t("units.m")} />
        <Stat label={t("dash.kish")} value={fmtNum(rep.development.kish, 2)} />
        <Stat label={t("dash.extra_rock")} value={fmtNum(rep.development.extra_t, 0)} unit={t("units.t")} />
        <Stat label={t("dash.extracted")} value={fmtNum(rep.stoping.extracted_t, 0)} unit={t("units.t")} />
      </div>}
      <div className="grid g2">
        {can("dispatch.view") && <Card title={t("menu.board")} actions={<Link to="/dispatch/board">{t("common.open")}</Link>}><BoardTable compact /></Card>}
        <Card title={t("dash.faces")} actions={<span className="row">{Object.entries(byStatus).map(([s, n]) => <span key={s}><Badge value={s} group="workflow.status" /> {n}</span>)}</span>}>
          <Table rows={faces} cols={[
            { key: "name", title: t("workflow.face"), render: (f) => <Link to={`/faces/${f.id}`}>{f.name}</Link> },
            { key: "status", title: t("workflow.face_status"), render: (f) => <Badge value={f.status} group="workflow.status" /> },
            { key: "cycle_no", title: t("workflow.cycle"), num: true },
            { key: "assignment", title: t("board.machine"), render: (f) => f.assignment ? `${f.assignment.machine || ""} · ${f.assignment.person || ""}` : "—" },
          ]} />
        </Card>
      </div>
      <Card title={t("menu.alerts")} actions={<Link to="/alerts">{t("common.open")}</Link>}>
        <Table rows={alerts} empty={t("alerts.none")} cols={[
          { key: "ts_mine", title: t("common.time") },
          { key: "severity", title: "", render: (a) => <Badge value={a.severity} /> },
          { key: "title", title: t("alerts.alert") },
          { key: "text", title: t("common.details") },
        ]} />
      </Card>
    </Page>
  );
}
