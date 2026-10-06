import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import Scene3D, { STATUS_COLOR } from "../components/Scene3D";
import { Badge, Card, Page } from "../components/ui";
import { useApi } from "../lib/hooks";

const hex = (n: number) => "#" + n.toString(16).padStart(6, "0");

export default function Mine3D() {
  const { t } = useTranslation();
  const { data } = useApi<any>("/api/mine/scene", 60000);
  const [levels, setLevels] = useState<Set<number> | null>(null);
  const [show, setShow] = useState({ stopes: true, orebody: true, machines: true, ramp: true });
  const [pick, setPick] = useState<any>(null);
  const lv = levels || new Set<number>(data?.levels || []);
  const ws = useMemo(() => (data?.workings || []).filter((w: any) => (w.type === "ramp" ? show.ramp : lv.has(w.level))), [data, levels, show.ramp]);
  const st = useMemo(() => show.stopes ? (data?.stopes || []).filter((s: any) => lv.has(s.level_bottom) || lv.has(s.level_top)) : [], [data, levels, show.stopes]);
  const machines = useMemo(() => (show.machines ? data?.machines || [] : []), [data, show.machines]);
  const faces = useMemo(() => data?.faces || [], [data]);
  return (
    <Page title={t("menu.mine3d")}>
      <Card>
        <div className="row" style={{ marginBottom: 8 }}>
          <b>{t("mine3d.levels")}:</b>
          {(data?.levels || []).map((l: number) => <label key={l} className="small"><input type="checkbox" checked={lv.has(l)} onChange={(e) => { const s = new Set(lv); if (e.target.checked) s.add(l); else s.delete(l); setLevels(s); }} />{l}</label>)}
          <span style={{ marginLeft: 16 }} />
          {Object.keys(show).map((k) => <label key={k} className="small"><input type="checkbox" checked={(show as any)[k]} onChange={(e) => setShow({ ...show, [k]: e.target.checked })} />{t(`mine3d.show.${k}`)}</label>)}
        </div>
        <div className="legend" style={{ marginBottom: 8 }}>
          {Object.entries(STATUS_COLOR).map(([s, c]) => <span key={s}><i style={{ background: hex(c) }} />{t(`workings.status.${s}`)}</span>)}
          <span><i style={{ background: "#e76f51" }} />{t("mine3d.stope_active")}</span><span><i style={{ background: "#ffd166" }} />{t("mine3d.face")}</span>
          <span><i style={{ background: "#ff006e" }} />Boomer</span><span><i style={{ background: "#8338ec" }} />Simba</span><span><i style={{ background: "#3a86ff" }} />{t("fleet.types.lhd")}</span>
        </div>
        {data && <Scene3D workings={ws} stopes={st} orebody={show.orebody ? data.orebody : null} machines={machines} faces={faces} onPick={setPick} height={620} />}
        <div className="small muted">{t("mine3d.hint")}</div>
      </Card>
      {pick && <Card title={pick.data.name || pick.data.number}>
        {pick.kind === "working" && <div className="kv"><div>{t("workings.type")}</div><div>{t(`workings.types.${pick.data.type}`)}</div><div>{t("common.status")}</div><div><Badge value={pick.data.status} group="workings.status" /></div><div>{t("common.level_short")}</div><div>{pick.data.level ?? "—"}</div><div>{t("workings.source")}</div><div>{t(`workings.sources.${pick.data.source}`)}</div></div>}
        {pick.kind === "stope" && <Link to={`/stopes/${pick.data.id}`}>{t("common.open")}</Link>}
        {pick.kind === "face" && <Link to={`/faces/${pick.data.id}`}>{t("common.open")} · {t(`workflow.status.${pick.data.status}`)}</Link>}
        {pick.kind === "machine" && <div>{pick.data.number} · <Badge value={pick.data.status} group="fleet.status" /></div>}
      </Card>}
    </Page>
  );
}
