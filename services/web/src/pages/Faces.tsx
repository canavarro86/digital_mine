import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Badge, Card, Page, Table } from "../components/ui";
import { qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";

export default function Faces() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const { timeMode } = useAuth();
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const { data } = useApi<any[]>("/api/workflow/faces" + qs({ kind, status }), 15000, [kind, status]);
  return (
    <Page title={t("menu.faces")} actions={<>
      <select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">{t("common.all")}</option><option value="dev">{t("common.kind.dev")}</option><option value="stope">{t("common.kind.stope")}</option></select>
      <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">{t("common.all")}</option>
        {["ready", "drilling", "drilled", "recalculated", "handed", "accepted", "charged", "wait_blast", "blasted", "mucking", "support", "surveyed", "analyzed", "done"].map((s) => <option key={s} value={s}>{t(`workflow.status.${s}`)}</option>)}
      </select>
    </>}>
      <Card>
        <Table rows={data} onRow={(f) => nav(`/faces/${f.id}`)} cols={[
          { key: "name", title: t("workflow.face") },
          { key: "kind", title: t("common.type"), render: (f) => t(`common.kind.${f.kind}`) },
          { key: "level", title: t("common.level_short"), num: true },
          { key: "chainage_label", title: t("workflow.chainage"), render: (f) => f.kind === "dev" ? f.chainage_label : "—" },
          { key: "status", title: t("workflow.face_status"), render: (f) => <Badge value={f.status} group="workflow.status" /> },
          { key: "since", title: t("workflow.since"), render: (f) => timeMode === "mine" ? f.since_mine : f.since_user },
          { key: "cycle_no", title: t("workflow.cycle"), num: true },
          { key: "assignment", title: t("board.machine"), render: (f) => f.assignment ? `${f.assignment.machine || ""} · ${f.assignment.person || ""}` : "—" },
          { key: "priority", title: t("workflow.priority"), num: true },
        ]} />
      </Card>
    </Page>
  );
}
