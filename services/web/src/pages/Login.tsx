import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { errText, loadLanguage } from "../lib/i18n";

export default function Login() {
  const { t, i18n } = useTranslation();
  const { login } = useAuth();
  const nav = useNavigate();
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [langs, setLangs] = useState<{ code: string; name: string }[]>([]);
  useEffect(() => { fetch("/api/i18n/languages").then((r) => r.json()).then(setLangs).catch(() => undefined); }, []);
  return (
    <div className="login">
      <form className="box" onSubmit={async (e) => {
        e.preventDefault();
        try { await login(u, p); nav("/"); } catch (x) { setErr(x); }
      }}>
        <div className="row"><img src="/favicon.svg" width={34} alt="" /><div><b style={{ fontSize: 18 }}>UG Blast Loop</b><div className="muted small">{t("auth.subtitle")}</div></div></div>
        <label className="field">{t("auth.username")}<input autoFocus value={u} onChange={(e) => setU(e.target.value)} /></label>
        <label className="field">{t("auth.password")}<input type="password" value={p} onChange={(e) => setP(e.target.value)} /></label>
        {!!err && <div className="error">{errText(err)}</div>}
        <button className="primary" type="submit">{t("auth.login")}</button>
        <select value={i18n.language} onChange={(e) => loadLanguage(e.target.value)}>
          {langs.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
        </select>
        <div className="muted small">admin / as · engineer / en · dispatcher / ds</div>
      </form>
    </div>
  );
}
