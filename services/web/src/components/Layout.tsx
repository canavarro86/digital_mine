import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { fmtTime, loadLanguage } from "../lib/i18n";

interface Item { to: string; key: string; perms?: string[]; ext?: boolean }
const MENU: [string, Item[]][] = [
  ["work", [
    { to: "/", key: "dashboard" },
    { to: "/dispatch/board", key: "board", perms: ["dispatch.view"] },
    { to: "/dispatch", key: "dispatch", perms: ["dispatch.view"] },
    { to: "/faces", key: "faces", perms: ["dispatch.view", "workings.view"] },
    { to: "/tablet", key: "tablet", perms: ["workflow.transition"] },
    { to: "/alerts", key: "alerts", perms: ["alerts.dispatch.view", "alerts.engineer.view", "alerts.admin.view"] },
  ]],
  ["mine", [
    { to: "/mine/3d", key: "mine3d" },
    { to: "/workings", key: "workings", perms: ["workings.view"] },
    { to: "/mine/import", key: "import", perms: ["mine.settings"] },
    { to: "/mine", key: "mine", perms: ["mine.settings"] },
  ]],
  ["blasting", [
    { to: "/passports", key: "passports", perms: ["passports.view"] },
    { to: "/typical", key: "typical", perms: ["passports.view"] },
    { to: "/rings", key: "rings", perms: ["passports.view"] },
    { to: "/geology", key: "geology", perms: ["geology.view"] },
    { to: "/explosives", key: "explosives", perms: ["explosives.view"] },
  ]],
  ["catalogs", [
    { to: "/fleet", key: "fleet", perms: ["fleet.view"] },
    { to: "/staff", key: "staff", perms: ["staff.view"] },
  ]],
  ["analytics", [
    { to: "/analysis", key: "analysis", perms: ["dispatch.view", "workings.view"] },
    { to: "/reports", key: "reports", perms: ["reports.view"] },
    { to: "/ai", key: "ai", perms: ["ai.use"] },
    { to: "/grafana/", key: "grafana", ext: true },
  ]],
  ["admin", [
    { to: "/settings", key: "settings", perms: ["system.settings"] },
    { to: "/users", key: "users", perms: ["users.manage"] },
    { to: "/console", key: "console", perms: ["console.use"] },
    { to: "/platform", key: "platform", perms: ["alerts.admin.view", "system.settings"] },
  ]],
];

function Clocks() {
  const { t } = useTranslation();
  const { user, mineTz, timeMode, setTimeMode } = useAuth();
  const { data } = useApi<any>("/api/clock", 60000);
  const [now, setNow] = useState(new Date());
  useEffect(() => { const id = setInterval(() => setNow(new Date()), 15000); return () => clearInterval(id); }, []);
  const f = (tz: string) => now.toLocaleTimeString(undefined, { timeZone: tz, hour: "2-digit", minute: "2-digit" });
  const place = (tz: string) => tz.split("/").pop()?.replace("_", " ");
  return (
    <div className="row">
      <span className="clock" title={mineTz}>{t("header.site")}: <b>{f(mineTz)}</b> <span className="muted small">({data?.country || place(mineTz)})</span></span>
      <span className="clock" title={user?.tz}>{t("header.me")}: <b>{f(user?.tz || "UTC")}</b> <span className="muted small">({place(user?.tz || "UTC")})</span></span>
      {data?.shift && <ShiftBadge data={data} now={now} />}
      <select value={timeMode} onChange={(e) => setTimeMode(e.target.value as "mine" | "me")} title={t("header.time_mode")}>
        <option value="mine">{t("header.time_site")}</option>
        <option value="me">{t("header.time_me")}</option>
      </select>
    </div>
  );
}

/** «Смена 2 · 08:00–16:00 · ВР в 15:00» и обратный отсчёт до ВР; во время окна — «Идут ВР до 16:00». */
export function ShiftBadge({ data, now }: { data: any; now: Date }) {
  const { t } = useTranslation();
  const { tz } = useAuth();
  const z = tz();
  const sh = data.shift;
  const nb = data.blast?.next;
  const cur = data.blast?.now;
  const left = nb ? Math.max(0, Math.round((new Date(nb.start).getTime() - now.getTime()) / 60000)) : null;
  const dur = (m: number) => (m >= 60 ? `${Math.floor(m / 60)} ${t("units.h")} ${String(m % 60).padStart(2, "0")} ${t("units.min")}` : `${m} ${t("units.min")}`);
  return (
    <span className="row" data-testid="shift-badge">
      <span className="badge info">{t("header.shift", { n: sh.shift_no })} · {fmtTime(sh.start, z)}–{fmtTime(sh.end, z)}
        {(data.blast?.windows || []).length > 0 && ` · ${t("header.blast_at", { time: data.blast.windows.map((w: any) => fmtTime(w.start, z)).join(", ") })}`}</span>
      {cur ? <span className="badge err">{t("header.blast_now", { until: fmtTime(cur.end, z) })}</span>
        : left !== null && left < 24 * 60 && <span className="badge warn" title={fmtTime(nb.start, z, true)}>{t("header.blast_in", { left: dur(left) })}</span>}
    </span>
  );
}

function LangSwitch() {
  const { i18n } = useTranslation();
  const { data } = useApi<{ code: string; name: string }[]>("/api/i18n/languages");
  const { reload } = useAuth();
  return (
    <select value={i18n.language} onChange={async (e) => {
      await api.patch("/api/auth/profile", { lang: e.target.value });
      await loadLanguage(e.target.value);
      await reload();
    }}>
      {(data || []).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
    </select>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { user, can, logout } = useAuth();
  const nav = useNavigate();
  const canAlerts = can("alerts.dispatch.view", "alerts.engineer.view", "alerts.admin.view");
  const { data: cnt } = useApi<{ open: number }>(canAlerts ? "/api/alerts/count" : null, 20000);
  return (
    <div className="app">
      <nav className="side">
        <div className="logo"><img src="/favicon.svg" width={22} alt="" /> UG Blast Loop</div>
        {MENU.map(([grp, items]) => {
          const vis = items.filter((i) => !i.perms || can(...i.perms));
          if (!vis.length) return null;
          return (
            <div key={grp}>
              <div className="grp">{t(`menu.groups.${grp}`)}</div>
              {vis.map((i) => i.ext
                ? <a key={i.to} href={i.to} target="_blank" rel="noreferrer">{t(`menu.${i.key}`)} ↗</a>
                : <NavLink key={i.to} to={i.to} end>{t(`menu.${i.key}`)}</NavLink>)}
            </div>
          );
        })}
      </nav>
      <div className="main">
        <div className="top">
          <Clocks />
          <div className="grow" />
          {canAlerts && <span className="bell" onClick={() => nav("/alerts")} title={t("menu.alerts")}>🔔{!!cnt?.open && <span className="n">{cnt.open}</span>}</span>}
          <LangSwitch />
          <Link to="/profile">{user?.full_name || user?.username} <span className="muted small">({user?.role_title?.[user.lang] || user?.role})</span></Link>
          <button className="small" onClick={() => { logout(); nav("/login"); }}>{t("common.logout")}</button>
        </div>
        <div className="content">
          {user?.must_change_password && <div className="notice">{t("auth.change_password_warning")} <Link to="/profile">{t("auth.change_password")}</Link></div>}
          {children}
        </div>
      </div>
    </div>
  );
}
