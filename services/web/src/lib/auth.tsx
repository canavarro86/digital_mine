import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "./api";
import { initialLanguage, loadLanguage } from "./i18n";

export interface User {
  id: number; username: string; full_name: string; role: string; role_title: Record<string, string>;
  permissions: string[]; lang: string; tz: string; must_change_password: boolean;
}

interface Ctx {
  user: User | null; ready: boolean; mineTz: string; timeMode: "mine" | "me";
  login: (u: string, p: string) => Promise<void>; logout: () => void; reload: () => Promise<void>;
  can: (...perms: string[]) => boolean; setTimeMode: (m: "mine" | "me") => void; tz: () => string;
}

const AuthCtx = createContext<Ctx>(null as unknown as Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [mineTz, setMineTz] = useState("UTC");
  const [timeMode, setTM] = useState<"mine" | "me">(() => {
    try { return (localStorage.getItem("dm_time") as "mine" | "me") || "mine"; } catch { return "mine"; }
  });

  const reload = useCallback(async () => {
    if (!getToken()) {
      await loadLanguage(initialLanguage()).catch(() => undefined);
      setUser(null); setReady(true); return;
    }
    try {
      const u = await api.get<User>("/api/auth/me");
      setUser(u);
      await loadLanguage(u.lang || "ru");
      const c = await api.get("/api/clock");
      setMineTz(c.mine_tz);
    } catch {
      setUser(null);
    }
    setReady(true);
  }, []);

  useEffect(() => {
    reload();
    const out = () => setUser(null);
    window.addEventListener("dm-logout", out);
    return () => window.removeEventListener("dm-logout", out);
  }, [reload]);

  const login = async (username: string, password: string) => {
    const fd = new URLSearchParams({ username, password });
    const r = await api.post<{ access_token: string }>("/api/auth/token", fd);
    setToken(r.access_token);
    await reload();
  };
  const logout = () => { setToken(null); setUser(null); };
  const can = (...perms: string[]) => !!user && perms.some((p) => user.permissions.includes(p));
  const setTimeMode = (m: "mine" | "me") => {
    setTM(m);
    try { localStorage.setItem("dm_time", m); } catch { /* ignore */ }
  };
  const tz = () => (timeMode === "mine" ? mineTz : user?.tz || "UTC");
  return (
    <AuthCtx.Provider value={{ user, ready, mineTz, timeMode, login, logout, reload, can, setTimeMode, tz }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
