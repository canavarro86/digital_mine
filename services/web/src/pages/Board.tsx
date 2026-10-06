import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ShiftBadge } from "../components/Layout";
import { Badge, Card, Page, Progress, Table } from "../components/ui";
import { qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";

export function BoardTable({ compact = false, level, work }: { compact?: boolean; level?: string; work?: string }) {
  const { t } = useTranslation();
  const { timeMode } = useAuth();
  const { data } = useApi<any>("/api/dispatch/board" + qs({ level, work_type: work }), 10000, [level, work]);
  const rows = data?.rows || [];
  const line = (r: any) => {
    const p = r.progress || {};
    const eta = timeMode === "mine" ? r.eta_mine : r.eta_user;
    if (r.work_type === "ring_drilling" && p.ring)
      return t("board.line_ring", { ring: p.ring, hole: p.hole, total: p.ring_holes });
    if (p.holes_total)
      return t("board.line_holes", { done: p.holes_done, total: p.holes_total }) + (eta ? ", " + t("board.eta", { time: eta, mode: t(`header.time_${timeMode === "mine" ? "site" : "me"}_short`) }) : "");
    return t(`workflow.status.${r.face_status}`, { defaultValue: r.face_status });
  };
  return (
    <Table rows={rows} empty={t("board.no_order")} cols={[
      { key: "person", title: t("board.person") },
      { key: "machine", title: t("board.machine") },
      { key: "face", title: t("board.face"), render: (r) => <Link to={`/faces/${r.face_id}`}>{r.face}</Link> },
      { key: "work_type", title: t("board.work"), render: (r) => t(`dispatch.work.${r.work_type}`) },
      { key: "state", title: t("board.state"), render: (r) => <div>{line(r)}{r.progress?.holes_total ? <Progress value={r.progress.holes_done} total={r.progress.holes_total} /> : null}</div> },
      ...(compact ? [] : [{ key: "face_status", title: t("workflow.face_status"), render: (r: any) => <Badge value={r.face_status} group="workflow.status" /> }]),
    ]} />
  );
}

export default function Board() {
  const { t } = useTranslation();
  const [level, setLevel] = useState("");
  const [work, setWork] = useState("");
  const { data: scene } = useApi<any>("/api/mine/scene");
  const { data: clock } = useApi<any>("/api/clock", 30000);
  return (
    <Page title={<>{t("menu.board")} {clock?.shift && <ShiftBadge data={clock} now={new Date()} />}</>} actions={<>
      <select value={level} onChange={(e) => setLevel(e.target.value)}><option value="">{t("common.all_levels")}</option>{(scene?.levels || []).map((l: number) => <option key={l} value={l}>{t("common.level", { l })}</option>)}</select>
      <select value={work} onChange={(e) => setWork(e.target.value)}><option value="">{t("common.all_works")}</option>{["drilling", "ring_drilling", "charging", "mucking", "support"].map((w) => <option key={w} value={w}>{t(`dispatch.work.${w}`)}</option>)}</select>
      <Link to="/mine/3d"><button>{t("board.on_plan")}</button></Link>
    </>}>
      <Card><BoardTable level={level} work={work} /></Card>
    </Page>
  );
}
