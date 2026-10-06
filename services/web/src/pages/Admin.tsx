import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Action, Badge, Card, ErrorBox, Field, Modal, Num, Page, Stat, Table, Tabs } from "../components/ui";
import { api, download } from "../lib/api";
import { useApi } from "../lib/hooks";
import { fmtNum } from "../lib/i18n";

export function Settings() {
  const { t } = useTranslation();
  const { data, reload } = useApi<any>("/api/settings");
  const { data: langs } = useApi<any[]>("/api/i18n/languages");
  const [s, setS] = useState<any>(null);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [tab, setTab] = useState("general");
  useEffect(() => { if (data) setS(JSON.parse(JSON.stringify(data))); }, [data]);
  if (!s) return null;
  const save = async (key: string, value: any) => { setErr(null); try { await api.put(`/api/settings/${key}`, { value }); setMsg(t("common.saved")); reload(); } catch (e) { setErr(e); } };
  const ai = s.ai || {};
  return (
    <Page title={t("menu.settings")} actions={<>
      <Action onClick={() => download("/api/settings/export")}>{t("settings.export")}</Action>
      <label className="btn">{t("settings.import")}<input type="file" hidden accept=".json" onChange={async (e) => { const f = e.target.files?.[0]; if (!f) return; try { const r = await api.post("/api/settings/import", JSON.parse(await f.text())); setMsg(t("settings.imported", { n: r.imported })); reload(); } catch (x) { setErr(x); } }} /></label>
    </>}>
      {msg && <div className="success">{msg}</div>}<ErrorBox error={err} />
      <Tabs value={tab} onChange={setTab} tabs={[["general", t("settings.general")], ["ai", t("settings.ai")], ["alerts", t("settings.alerts")], ["economics", t("settings.economics")], ["telegram", "Telegram"]]} />
      {tab === "general" && <Card>
        <div className="form">
          <Field label={t("settings.default_language")}><select value={s.default_language} onChange={(e) => setS({ ...s, default_language: e.target.value })}>{(langs || []).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}</select></Field>
          <Action className="primary" onClick={() => save("default_language", s.default_language)}>{t("common.save")}</Action>
          <Field label={t("settings.mines_path")}><input value={s.mines_path || ""} onChange={(e) => setS({ ...s, mines_path: e.target.value })} /></Field>
          <Action className="primary" onClick={() => save("mines_path", s.mines_path)}>{t("common.save")}</Action>
        </div>
        <div className="small muted" style={{ marginTop: 8 }}>{t("settings.languages_note", { list: (langs || []).map((l) => l.code).join(", ") })}</div>
      </Card>}
      {tab === "ai" && <Card>
        <div className="form">
          <Field label={t("ai.provider")}><select value={ai.provider} onChange={(e) => setS({ ...s, ai: { ...ai, provider: e.target.value, model: "" } })}>
            <option value="demo">{t("ai.demo_provider")}</option>{Object.entries(ai.providers || {}).map(([k, p]: any) => <option key={k} value={k}>{p.label}</option>)}</select></Field>
          {ai.provider !== "demo" && <Field label={t("ai.model")}><select value={ai.model || ai.providers?.[ai.provider]?.default_model} onChange={(e) => setS({ ...s, ai: { ...ai, model: e.target.value } })}>
            {Object.keys(ai.providers?.[ai.provider]?.models || {}).map((m) => <option key={m}>{m}</option>)}</select></Field>}
          <Field label={t("ai.monthly_budget")}><Num value={ai.monthly_budget_usd} onChange={(v) => setS({ ...s, ai: { ...ai, monthly_budget_usd: v } })} /></Field>
          <Field label={t("ai.max_per_day")}><Num value={ai.max_requests_per_day} step="1" onChange={(v) => setS({ ...s, ai: { ...ai, max_requests_per_day: v } })} /></Field>
        </div>
        <h3>{t("ai.keys")}</h3>
        <table className="t"><thead><tr><th>{t("ai.provider")}</th><th>{t("ai.key_state")}</th><th>{t("ai.new_key")}</th><th>{t("ai.prices")}</th></tr></thead>
          <tbody>{Object.entries(ai.providers || {}).map(([k, p]: any) => <tr key={k}><td>{p.label}</td>
            <td>{p.api_key_set ? <Badge value="ok" /> : <span className="muted">{t("ai.no_key")}</span>}</td>
            <td><input type="password" autoComplete="off" value={keys[k] || ""} onChange={(e) => setKeys({ ...keys, [k]: e.target.value })} placeholder="sk-..." /></td>
            <td className="small">{Object.entries(p.models || {}).map(([m, pr]: any) => `${m}: $${pr.price_in}/$${pr.price_out}`).join("; ")}</td></tr>)}</tbody></table>
        <div className="small muted">{t("ai.key_note")}</div>
        <Action className="primary" onClick={() => {
          const providers = Object.fromEntries(Object.entries(ai.providers || {}).map(([k, p]: any) => [k, { ...p, ...(keys[k] ? { api_key: keys[k] } : {}) }]));
          setKeys({});
          return save("ai", { ...ai, providers });
        }}>{t("common.save")}</Action>
      </Card>}
      {tab === "alerts" && <Card>
        <div className="form">{Object.entries(s.alerts || {}).map(([k, v]) => <Field key={k} label={t(`settings.thresholds.${k}`, { defaultValue: k })}><Num value={v} onChange={(x) => setS({ ...s, alerts: { ...s.alerts, [k]: x } })} /></Field>)}</div>
        <Action className="primary" onClick={() => save("alerts", s.alerts)}>{t("common.save")}</Action>
      </Card>}
      {tab === "economics" && <Card>
        <h3>{t("settings.metal_prices")}</h3>
        <div className="form">{Object.entries(s.economics?.metal_prices || {}).map(([m, p]: any) => <Field key={m} label={`${m}, ${p.unit}`}><Num value={p.price} onChange={(v) => setS({ ...s, economics: { ...s.economics, metal_prices: { ...s.economics.metal_prices, [m]: { ...p, price: v } } } })} /></Field>)}</div>
        <h3>{t("settings.recovery")}</h3>
        <div className="form">{Object.entries(s.economics?.recovery || {}).map(([m, v]: any) => <Field key={m} label={m}><Num value={v} onChange={(x) => setS({ ...s, economics: { ...s.economics, recovery: { ...s.economics.recovery, [m]: x } } })} /></Field>)}</div>
        <h3>{t("settings.costs")}</h3>
        <div className="form">{Object.entries(s.economics?.costs || {}).map(([k, v]: any) => <Field key={k} label={t(`settings.cost.${k}`, { defaultValue: k })}><Num value={v} onChange={(x) => setS({ ...s, economics: { ...s.economics, costs: { ...s.economics.costs, [k]: x } } })} /></Field>)}</div>
        <Action className="primary" onClick={() => save("economics", s.economics)}>{t("common.save")}</Action>
      </Card>}
      {tab === "telegram" && <Card>
        <div className="form">
          <Field label={t("settings.tg_enabled")}><input type="checkbox" checked={!!s.telegram?.enabled} onChange={(e) => setS({ ...s, telegram: { ...s.telegram, enabled: e.target.checked } })} /></Field>
          <Field label={t("settings.tg_token")}><input type="password" placeholder={s.telegram?.bot_token_set ? "••••••" : ""} onChange={(e) => setS({ ...s, telegram: { ...s.telegram, bot_token: e.target.value } })} /></Field>
          <Field label={t("settings.tg_chat")}><input value={s.telegram?.chat_id || ""} onChange={(e) => setS({ ...s, telegram: { ...s.telegram, chat_id: e.target.value } })} /></Field>
          <Action className="primary" onClick={() => save("telegram", s.telegram)}>{t("common.save")}</Action>
        </div>
      </Card>}
    </Page>
  );
}

export function Users() {
  const { t, i18n } = useTranslation();
  const [tab, setTab] = useState("users");
  const { data: users, reload } = useApi<any[]>("/api/admin/users");
  const { data: roles, reload: rr } = useApi<any[]>("/api/admin/roles");
  const { data: perms } = useApi<string[]>("/api/admin/permissions");
  const { data: audit } = useApi<any[]>(tab === "audit" ? "/api/admin/audit?limit=300" : null, 0, [tab]);
  const [u, setU] = useState<any>(null);
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const roleName = (id: number) => { const x = (roles || []).find((y) => y.id === id); return x ? x.title?.[i18n.language] || x.name : id; };
  return (
    <Page title={t("menu.users")} actions={<>
      {tab === "users" && <button className="primary" onClick={() => setU({ role_id: roles?.[1]?.id, lang: "ru", tz: "America/Santiago", active: true })}>+ {t("users.add")}</button>}
      {tab === "roles" && <button className="primary" onClick={() => setR({ name: "", title: {}, permissions: [], grafana_role: "Viewer" })}>+ {t("users.add_role")}</button>}
    </>}>
      <Tabs value={tab} onChange={setTab} tabs={[["users", t("users.users")], ["roles", t("users.roles")], ["audit", t("users.audit")]]} />
      {tab === "users" && <Card><Table rows={users} onRow={setU} cols={[
        { key: "username", title: t("auth.username") }, { key: "full_name", title: t("profile.full_name") },
        { key: "role_id", title: t("users.role"), render: (x) => roleName(x.role_id) }, { key: "lang", title: t("profile.language") }, { key: "tz", title: t("profile.timezone") },
        { key: "active", title: t("common.active"), render: (x) => x.active ? "✓" : "—" }, { key: "must_change_password", title: t("users.must_change"), render: (x) => x.must_change_password ? "⚠" : "" },
      ]} /></Card>}
      {tab === "roles" && <Card><Table rows={roles} onRow={setR} cols={[
        { key: "name", title: t("users.role") }, { key: "title", title: t("common.name"), render: (x) => x.title?.[i18n.language] || x.name },
        { key: "permissions", title: t("users.permissions"), render: (x) => <span className="small">{x.permissions.length}: {x.permissions.join(", ")}</span> },
        { key: "grafana_role", title: "Grafana" }, { key: "builtin", title: t("users.builtin"), render: (x) => x.builtin ? "✓" : "" },
      ]} /></Card>}
      {tab === "audit" && <Card><Table rows={audit} cols={[
        { key: "ts", title: t("common.time"), render: (a) => a.ts.slice(0, 19).replace("T", " ") }, { key: "username", title: t("common.user") },
        { key: "action", title: t("users.action") }, { key: "entity", title: t("users.entity") }, { key: "entity_id", title: "ID" },
        { key: "details", title: t("common.details"), render: (a) => <span className="small">{JSON.stringify(a.details).slice(0, 160)}</span> },
      ]} /></Card>}
      {u && <Modal title={u.id ? u.username : t("users.add")} onClose={() => setU(null)} footer={<Action className="primary" onClick={async () => {
        setErr(null);
        try { if (u.id) await api.put(`/api/admin/users/${u.id}`, u); else await api.post("/api/admin/users", u); setU(null); reload(); } catch (e) { setErr(e); }
      }}>{t("common.save")}</Action>}>
        <div className="form">
          <Field label={t("auth.username")}><input value={u.username || ""} disabled={!!u.id} onChange={(e) => setU({ ...u, username: e.target.value })} /></Field>
          <Field label={u.id ? t("users.reset_password") : t("auth.password")}><input type="password" value={u.password || ""} onChange={(e) => setU({ ...u, password: e.target.value })} /></Field>
          <Field label={t("profile.full_name")}><input value={u.full_name || ""} onChange={(e) => setU({ ...u, full_name: e.target.value })} /></Field>
          <Field label={t("users.role")}><select value={u.role_id} onChange={(e) => setU({ ...u, role_id: Number(e.target.value) })}>{(roles || []).map((x) => <option key={x.id} value={x.id}>{x.title?.[i18n.language] || x.name}</option>)}</select></Field>
          <Field label={t("profile.language")}><input value={u.lang} onChange={(e) => setU({ ...u, lang: e.target.value })} /></Field>
          <Field label={t("profile.timezone")}><input value={u.tz} onChange={(e) => setU({ ...u, tz: e.target.value })} /></Field>
          <Field label={t("common.active")}><input type="checkbox" checked={u.active} onChange={(e) => setU({ ...u, active: e.target.checked })} /></Field>
        </div>
        <ErrorBox error={err} />
      </Modal>}
      {r && <Modal wide title={r.id ? r.name : t("users.add_role")} onClose={() => setR(null)} footer={<Action className="primary" onClick={async () => {
        setErr(null);
        try { if (r.id) await api.put(`/api/admin/roles/${r.id}`, r); else await api.post("/api/admin/roles", r); setR(null); rr(); } catch (e) { setErr(e); }
      }}>{t("common.save")}</Action>}>
        <div className="form">
          <Field label={t("users.role_code")}><input value={r.name} disabled={r.builtin} onChange={(e) => setR({ ...r, name: e.target.value })} /></Field>
          {["ru", "en", "es"].map((l) => <Field key={l} label={`${t("common.name")} (${l})`}><input value={r.title?.[l] || ""} onChange={(e) => setR({ ...r, title: { ...r.title, [l]: e.target.value } })} /></Field>)}
          <Field label="Grafana"><select value={r.grafana_role} onChange={(e) => setR({ ...r, grafana_role: e.target.value })}>{["Viewer", "Editor", "Admin"].map((g) => <option key={g}>{g}</option>)}</select></Field>
        </div>
        <h3>{t("users.permissions")}</h3>
        <div className="grid g3">{(perms || []).map((p) => <label key={p} className="small"><input type="checkbox" checked={r.permissions.includes(p)} onChange={(e) => setR({ ...r, permissions: e.target.checked ? [...r.permissions, p] : r.permissions.filter((x: string) => x !== p) })} /> {t(`perm.${p}`, { defaultValue: p })} <span className="muted">({p})</span></label>)}</div>
        {r.id && !r.builtin && <Action className="danger" confirm={t("common.confirm_delete")} onClick={async () => { await api.del(`/api/admin/roles/${r.id}`); setR(null); rr(); }}>{t("common.delete")}</Action>}
        <ErrorBox error={err} />
      </Modal>}
    </Page>
  );
}

export function Console() {
  const { t } = useTranslation();
  const { data: st, reload, error } = useApi<any>("/api/emulator/state", 3000);
  const [speed, setSpeed] = useState(60);
  const call = async (a: string, body: any = {}) => { await api.post(`/api/emulator/${a}`, body); reload(); };
  useEffect(() => { if (st?.speed) setSpeed(st.speed); }, [st?.speed]);
  if (!st) return <Page title={t("menu.console")}><ErrorBox error={error} /></Page>;
  const sc = (name: string) => (
    <div key={name} className="row" style={{ justifyContent: "space-between", borderBottom: "1px solid var(--line)", padding: "4px 0" }}>
      <span>{t(`emulator.sc.${name}`)} <span className="muted small">→ {t(`analysis.causes.${name}`, { defaultValue: "—" })}</span></span>
      <select value={st.scenarios[name] || ""} onChange={(e) => call("scenarios", { [name]: e.target.value || null })}>
        <option value="">{t("emulator.off")}</option>{st.catalog.strengths.map((s: string) => <option key={s} value={s}>{t(`emulator.strength.${s}`)}</option>)}
      </select>
    </div>
  );
  return (
    <Page title={t("menu.console")} actions={<>
      <Badge value={st.running ? "working" : "idle"} group="emulator.state" />
      {!st.running ? <Action className="primary" onClick={() => call("start", { speed })}>▶ {t("emulator.start")}</Action> : <Action onClick={() => call("pause")}>⏸ {t("emulator.pause")}</Action>}
      <Action confirm={t("emulator.reset_confirm")} onClick={() => call("reset")}>⟲ {t("emulator.reset")}</Action>
    </>}>
      <div className="grid g4" style={{ marginBottom: 12 }}>
        {Object.entries(st.stats).map(([k, v]) => <Stat key={k} label={t(`emulator.stats.${k}`)} value={fmtNum(v, 0)} />)}
      </div>
      <div className="grid g3">
        <Card title={t("emulator.speed")}>
          <input type="range" min={1} max={500} value={speed} onChange={(e) => setSpeed(Number(e.target.value))} style={{ width: "100%" }} />
          <div className="row"><b>×{speed}</b>{[1, 10, 60, 200, 500].map((v) => <button key={v} className="small" onClick={() => { setSpeed(v); call("speed", { speed: v }); }}>×{v}</button>)}
            <Action className="small primary" onClick={() => call("speed", { speed })}>{t("common.apply")}</Action></div>
          <h3>{t("emulator.dispatch")}</h3>
          <label className="small"><input type="checkbox" checked={st.auto_dispatch} onChange={(e) => call("auto", { auto_dispatch: e.target.checked })} /> {t("emulator.auto_dispatch")}</label>
          <h3>{t("emulator.load")}</h3>
          <div className="row"><label className="small"><input type="checkbox" checked={st.load.enabled} onChange={(e) => call("load", { enabled: e.target.checked })} /> {t("emulator.load_enable")}</label>
            <Num value={st.load.rate} onChange={(v) => call("load", { rate: v })} style={{ width: 80 }} /> {t("emulator.events_per_s")}</div>
          <div className="small muted">{t("emulator.load_note")}</div>
        </Card>
        <Card title={t("emulator.dev_scenarios")}>{st.catalog.dev.map(sc)}</Card>
        <Card title={t("emulator.stope_scenarios")}>{st.catalog.stope.map(sc)}<h3>{t("emulator.ops_scenarios")}</h3>{st.catalog.ops.map(sc)}</Card>
      </div>
      <Card title={t("emulator.log")}>
        <Table rows={st.log} cols={[{ key: "ts", title: t("common.time"), render: (l) => l.ts.slice(11, 19) }, { key: "msg", title: t("emulator.event") }, { key: "scenario", title: t("emulator.scenario"), render: (l) => l.scenario ? t(`analysis.causes.${l.scenario}`, { defaultValue: l.scenario }) : "" }]} />
      </Card>
    </Page>
  );
}

export function Platform() {
  const { t } = useTranslation();
  const { data } = useApi<any>("/api/platform", 15000);
  const mem = Array.isArray(data?.memory) ? data.memory.map((m: any) => ({ pod: m.labels.pod, mb: m.value / 1048576 })).sort((a: any, b: any) => b.mb - a.mb) : [];
  const total = Array.isArray(data?.total) && data.total[0] ? data.total[0].value / 1073741824 : null;
  return (
    <Page title={t("menu.platform")} actions={<a href="/grafana/" target="_blank" rel="noreferrer"><button>Grafana ↗</button></a>}>
      <div className="grid g4" style={{ marginBottom: 12 }}>
        <Stat label={t("platform.total_memory")} value={fmtNum(total, 2)} unit={t("units.gb")} />
        <Stat label={t("platform.services_up")} value={Array.isArray(data?.up) ? `${data.up.filter((x: any) => x.value === 1).length} / ${data.up.length}` : "—"} />
        {Array.isArray(data?.replicas) && data.replicas.map((r: any) => <Stat key={r.labels.horizontalpodautoscaler} label={`HPA ${r.labels.horizontalpodautoscaler}`} value={r.value} />)}
      </div>
      <Card title={t("platform.memory")}><Table rows={mem} cols={[{ key: "pod", title: "Pod" }, { key: "mb", title: t("units.mb"), num: true, render: (r) => fmtNum(r.mb, 0) }]} /></Card>
    </Page>
  );
}
