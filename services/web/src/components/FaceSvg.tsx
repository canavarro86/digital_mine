import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export const HOLE_COLORS: Record<string, string> = {
  empty: "#ffffff", cut: "#d62728", stoping: "#2ca02c", helper: "#17becf", contour: "#1f77b4", lifter: "#9467bd",
};

/** Вид на забой: контур, шпуры, номера и замедления; перетаскивание шпуров (editable). */
export default function FaceSvg({ result, editable = false, onMove, onSelect, selected, size = 560, showDelays = true, actual = false }: {
  result: any; editable?: boolean; onMove?: (id: number, x: number, y: number, done: boolean) => void;
  onSelect?: (id: number) => void; selected?: number | null; size?: number; showDelays?: boolean; actual?: boolean;
}) {
  const { t } = useTranslation();
  const ref = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<number | null>(null);
  if (!result?.contour) return null;
  const xs = result.contour.map((p: number[]) => p[0]);
  const ys = result.contour.map((p: number[]) => p[1]);
  const minx = Math.min(...xs) - 0.7, maxx = Math.max(...xs) + 0.7, miny = Math.min(...ys) - 0.7, maxy = Math.max(...ys) + 0.7;
  const sc = size / Math.max(maxx - minx, maxy - miny);
  const W = (maxx - minx) * sc, H = (maxy - miny) * sc;
  const X = (x: number) => (x - minx) * sc;
  const Y = (y: number) => H - (y - miny) * sc;
  const toWorld = (e: React.PointerEvent) => {
    const r = ref.current!.getBoundingClientRect();
    return [(e.clientX - r.left) * (W / r.width) / sc + minx, (H - (e.clientY - r.top) * (H / r.height)) / sc + miny];
  };
  return (
    <div>
      <svg ref={ref} className="svgbox" width="100%" viewBox={`0 0 ${W} ${H}`} style={{ maxWidth: size, touchAction: "none" }}
        onPointerMove={(e) => { if (drag !== null && onMove) { const [x, y] = toWorld(e); onMove(drag, x, y, false); } }}
        onPointerUp={(e) => { if (drag !== null && onMove) { const [x, y] = toWorld(e); onMove(drag, x, y, true); } setDrag(null); }}>
        <polygon points={result.contour.map((p: number[]) => `${X(p[0])},${Y(p[1])}`).join(" ")} fill="#f6f7f9" stroke="#111" strokeWidth={1.8} />
        <line x1={X(0)} y1={0} x2={X(0)} y2={H} stroke="#aaa" strokeDasharray="6 4" />
        {result.holes.map((h: any) => {
          const r = Math.max(4, ((h.diameter || 45) / 1000) * sc * 1.1);
          let stroke = "#000";
          if (h.flag || h.zone === "overloaded") stroke = "#ff7f0e";
          if (h.zone === "underloaded") stroke = "#d62728";
          const fill = h.not_drilled ? "#fff" : HOLE_COLORS[h.type] || "#555";
          return (
            <g key={h.id} style={{ cursor: editable && h.type !== "empty" ? "grab" : "pointer" }}
              onPointerDown={(e) => { onSelect?.(h.id); if (editable) { (e.target as Element).setPointerCapture?.(e.pointerId); setDrag(h.id); } }}>
              {actual && h.toe_x !== undefined && !h.not_drilled && (
                <line x1={X(h.design_x ?? h.x)} y1={Y(h.design_y ?? h.y)} x2={X(h.toe_x)} y2={Y(h.toe_y)} stroke="#e76f51" strokeWidth={1.5} />)}
              <circle cx={X(h.x)} cy={Y(h.y)} r={selected === h.id ? r + 3 : r} fill={fill} stroke={stroke}
                strokeWidth={h.flag || h.zone && h.zone !== "ok" ? 2.5 : 1} strokeDasharray={h.not_drilled ? "3 2" : undefined} />
              {h.type !== "empty" && <text x={X(h.x) + r + 1} y={Y(h.y) - r} fontSize={9}>{h.id}{showDelays && h.delay_ms !== undefined ? `/${h.delay_ms}` : ""}</text>}
            </g>
          );
        })}
      </svg>
      <div className="legend">
        {Object.entries(HOLE_COLORS).map(([k, c]) => <span key={k}><i style={{ background: c }} />{t(`dev_passport.hole_types.${k}`)}</span>)}
        {actual && <><span><i style={{ background: "#fff", borderColor: "#ff7f0e", borderWidth: 2 }} />{t("workflow.zone.overloaded")}</span><span><i style={{ background: "#fff", borderColor: "#d62728", borderWidth: 2 }} />{t("workflow.zone.underloaded")}</span></>}
      </div>
    </div>
  );
}
