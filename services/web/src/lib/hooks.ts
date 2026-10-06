import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Загрузка данных с API с повтором по интервалу (мс). */
export function useApi<T = any>(path: string | null, interval = 0, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const alive = useRef(true);
  const seq = useRef(0);  // ответ на устаревший запрос (путь уже сменился) не перезаписывает данные
  const load = useCallback(async () => {
    if (!path) return;
    const my = ++seq.current;
    setLoading(true);
    try {
      const d = await api.get<T>(path);
      if (alive.current && my === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (alive.current && my === seq.current) setError(e);
    } finally {
      if (alive.current && my === seq.current) setLoading(false);
    }
  }, [path, ...deps]);
  useEffect(() => {
    alive.current = true;
    load();
    if (!interval) return () => { alive.current = false; };
    const id = window.setInterval(load, interval);
    return () => { alive.current = false; window.clearInterval(id); };
  }, [load, interval]);
  return { data, error, loading, reload: load, setData };
}
