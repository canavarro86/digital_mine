import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Action, Card, Field, Page } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { loadLanguage } from "../lib/i18n";

const TZS = ["America/Santiago", "Asia/Bangkok", "Europe/Moscow", "UTC", "America/Lima", "Australia/Perth", "Asia/Almaty", "Europe/Madrid"];

export default function Profile() {
  const { t } = useTranslation();
  const { user, reload } = useAuth();
  const { data: langs } = useApi<{ code: string; name: string }[]>("/api/i18n/languages");
  const [lang, setLang] = useState(user?.lang || "ru");
  const [tz, setTz] = useState(user?.tz || "UTC");
  const [name, setName] = useState(user?.full_name || "");
  const [pw, setPw] = useState({ old_password: "", new_password: "" });
  const [ok, setOk] = useState("");
  return (
    <Page title={t("profile.title")}>
      <div className="grid g2">
        <Card title={t("profile.settings")}>
          <div className="form">
            <Field label={t("profile.full_name")}><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label={t("profile.language")}>
              <select value={lang} onChange={(e) => setLang(e.target.value)}>{(langs || []).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}</select>
            </Field>
            <Field label={t("profile.timezone")}>
              <input list="tzs" value={tz} onChange={(e) => setTz(e.target.value)} />
              <datalist id="tzs">{TZS.map((z) => <option key={z} value={z} />)}</datalist>
            </Field>
            <Action className="primary" onClick={async () => {
              await api.patch("/api/auth/profile", { lang, tz, full_name: name });
              await loadLanguage(lang);
              await reload();
              setOk(t("common.saved"));
            }}>{t("common.save")}</Action>
          </div>
          {ok && <div className="success">{ok}</div>}
        </Card>
        <Card title={t("auth.change_password")}>
          <div className="form">
            <Field label={t("auth.old_password")}><input type="password" value={pw.old_password} onChange={(e) => setPw({ ...pw, old_password: e.target.value })} /></Field>
            <Field label={t("auth.new_password")}><input type="password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
            <Action className="primary" onClick={async () => { await api.post("/api/auth/password", pw); await reload(); setOk(t("common.saved")); }}>{t("common.save")}</Action>
          </div>
        </Card>
      </div>
    </Page>
  );
}
