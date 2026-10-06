// Клиент API: JWT из localStorage, ошибки — коды из locales (errors.*)
export class ApiError extends Error {
  code: string;
  params: Record<string, unknown>;
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    const d = typeof detail === "object" && detail ? detail : { code: String(detail ?? "errors.unknown") };
    super(d.code);
    this.code = d.code || "errors.unknown";
    this.params = d.params || {};
    this.status = status;
    this.detail = d;
  }
}

const TOKEN = "dm_token";
export const getToken = () => {
  try { return localStorage.getItem(TOKEN); } catch { return null; }
};
export const setToken = (t: string | null) => {
  try { if (t) localStorage.setItem(TOKEN, t); else localStorage.removeItem(TOKEN); } catch { /* приватный режим */ }
};

async function request<T>(method: string, path: string, body?: unknown, raw = false): Promise<T> {
  const headers: Record<string, string> = {};
  const t = getToken();
  if (t) headers.Authorization = `Bearer ${t}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData || body instanceof URLSearchParams) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const r = await fetch(path, { method, headers, body: payload });
  if (r.status === 401 && !path.endsWith("/auth/token")) {
    setToken(null);
    window.dispatchEvent(new Event("dm-logout"));
  }
  if (!r.ok) {
    let detail: any = "errors.http_" + r.status;
    try { detail = (await r.json()).detail; } catch { /* не JSON */ }
    throw new ApiError(r.status, detail);
  }
  if (raw) return r as unknown as T;
  const ct = r.headers.get("content-type") || "";
  return (ct.includes("json") ? r.json() : r.text()) as Promise<T>;
}

export const api = {
  get: <T = any>(p: string) => request<T>("GET", p),
  post: <T = any>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  put: <T = any>(p: string, b?: unknown) => request<T>("PUT", p, b ?? {}),
  patch: <T = any>(p: string, b?: unknown) => request<T>("PATCH", p, b ?? {}),
  del: <T = any>(p: string) => request<T>("DELETE", p),
  upload: <T = any>(p: string, fd: FormData) => request<T>("POST", p, fd),
};

/** Скачивание файла (PDF, DXF, CSV, ZIP) с авторизацией. */
export async function download(path: string, fallbackName = "file") {
  const r = await request<Response>("GET", path, undefined, true);
  const blob = await r.blob();
  const cd = r.headers.get("content-disposition") || "";
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = m ? decodeURIComponent(m[1]) : fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

export const qs = (o: Record<string, unknown>) =>
  "?" + Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");
