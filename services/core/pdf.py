"""PDF (WeasyPrint): паспорт проходки «как настоящий», веера, отчеты. Все надписи — через t(key, lang)."""
from __future__ import annotations

import html
from typing import Callable

from . import drawing

CSS = """
@page { size: A4 landscape; margin: 10mm; @bottom-right { content: counter(page) " / " counter(pages); font-size: 8pt; } }
body { font-family: 'DejaVu Sans', sans-serif; font-size: 8.5pt; color: #111; }
h1 { font-size: 13pt; margin: 0 0 2mm 0; } h2 { font-size: 10pt; margin: 3mm 0 1mm 0; }
table { border-collapse: collapse; width: 100%; } td, th { border: 0.6pt solid #444; padding: 1px 3px; }
th { background: #eee; } .grid { display: flex; gap: 6mm; } .col { flex: 1; }
.small { font-size: 7.5pt; } .warn { color: #b00; } .sign td { height: 9mm; vertical-align: bottom; }
.legend span { display: inline-block; margin-right: 8px; } .dot { display:inline-block; width:8px; height:8px; border-radius:50%; border:1px solid #000; margin-right:2px; }
"""


def _e(x) -> str:
    return html.escape("" if x is None else str(x))


def render(html_body: str, title: str) -> bytes:
    from weasyprint import HTML

    doc = f"<html><head><meta charset='utf-8'><title>{_e(title)}</title><style>{CSS}</style></head><body>{html_body}</body></html>"
    return HTML(string=doc).write_pdf()


def passport_pdf(p: dict, result: dict, t: Callable[[str], str], meta: dict) -> bytes:
    """meta: mine, working, number, date (по времени рудника), signatures {made, checked, approved}."""
    lab = {"m": t("units.m"), "lookout": t("dev_passport.lookout")}
    ind = result["indicators"]
    inp = result["input"]
    face = drawing.face_view(result, lab)
    sec = drawing.section_aa(result, lab)
    legend = "".join(f"<span><i class='dot' style='background:{c}'></i>{_e(t('dev_passport.hole_types.' + k))}</span>"
                     for k, c in drawing.COLORS.items())
    rows = []
    for h in result["holes"]:
        if h["type"] == "empty":
            charge = "—"
        else:
            charge = f"{h.get('charge_kg', 0):.2f}" + (f" ({h['cartridges']} {t('dev_passport.cart')})" if h.get("cartridges") else "")
        rows.append(f"<tr><td>{h['id']}</td><td>{_e(t('dev_passport.hole_types.' + h['type']))}</td>"
                    f"<td>{h.get('diameter', 0):.0f}</td><td>{h.get('length', 0):.2f}</td><td>{h.get('angle', 0):.1f}</td>"
                    f"<td>{charge}</td><td>{h.get('stemming', 0):.2f}</td><td>{h.get('delay_ms', '') if h['type'] != 'empty' else ''}</td></tr>")
    ind_rows = [
        ("dev_passport.area", f"{ind['area']:.2f} {t('units.m2')}"),
        ("dev_passport.depth", f"{ind['depth']:.2f} {t('units.m')}"),
        ("dev_passport.kish", f"{ind['kish']:.2f}"),
        ("dev_passport.advance", f"{ind['advance']:.2f} {t('units.m')}"),
        ("dev_passport.volume", f"{ind['volume']:.1f} {t('units.m3')}"),
        ("dev_passport.q", f"{ind['q_actual']:.2f} {t('units.kg_m3')} ({t('dev_passport.pokrovsky')}: {ind['q_pokrovsky']:.2f})"),
        ("dev_passport.explosive_cycle", f"{ind['explosive_kg']:.1f} {t('units.kg')}"),
        ("dev_passport.kg_per_m", f"{ind['kg_per_m']:.1f} {t('units.kg')}"),
        ("dev_passport.holes", f"{ind['holes_total']} ({t('dev_passport.pokrovsky')}: {ind['holes_pokrovsky']})"),
        ("dev_passport.drill_m", f"{ind['drill_m']:.1f} {t('units.m')}"),
        ("dev_passport.detonators", f"{ind['detonators']}"),
    ]
    warn = "".join(f"<div class='warn'>⚠ {_e(t('errors.' + w['code']))}</div>" for w in result.get("warnings", []))
    sig = meta.get("signatures") or {}
    body = f"""
    <h1>{_e(t('dev_passport.title'))} № {_e(meta.get('number', ''))}</h1>
    <div class='small'>{_e(meta.get('mine', ''))} · {_e(t('workings.working'))}: <b>{_e(meta.get('working', ''))}</b> ·
      {_e(t('dev_passport.section'))}: {_e(t('dev_passport.shapes.' + inp['section'].get('shape', 'arch')))}
      {inp['section'].get('width')}×{inp['section'].get('height')} {_e(t('units.m'))} ·
      {_e(t('geology.f'))} = {inp.get('rock', {}).get('f')} · {_e(t('explosives.explosive'))}: {_e(inp['explosive'].get('name'))} ·
      {_e(t('dev_passport.cut'))}: {_e(t('dev_passport.cut_types.' + inp.get('cut', {}).get('type', 'prismatic')))}</div>
    <div class='grid'>
      <div class='col'><h2>{_e(t('dev_passport.face_view'))}</h2>{face}<div class='legend small'>{legend}</div></div>
      <div class='col'><h2>{_e(t('dev_passport.indicators'))}</h2>
        <table>{''.join(f"<tr><td>{_e(t(k))}</td><td><b>{v}</b></td></tr>" for k, v in ind_rows)}</table>
        <h2>{_e(t('dev_passport.section_aa'))}</h2>{sec}{warn}</div>
    </div>
    <h2 style='page-break-before: always'>{_e(t('dev_passport.holes_table'))}</h2>
    <table class='small'><tr><th>№</th><th>{_e(t('dev_passport.type'))}</th><th>{_e(t('dev_passport.diameter_mm'))}</th>
      <th>{_e(t('dev_passport.length_m'))}</th><th>{_e(t('dev_passport.angle_deg'))}</th><th>{_e(t('dev_passport.charge'))}</th>
      <th>{_e(t('dev_passport.stemming_m'))}</th><th>{_e(t('dev_passport.delay_ms'))}</th></tr>{''.join(rows)}</table>
    <h2>{_e(t('dev_passport.signatures'))}</h2>
    <table class='sign'><tr><td>{_e(t('dev_passport.made'))}: {_e(sig.get('made', ''))}</td>
      <td>{_e(t('dev_passport.checked'))}: {_e(sig.get('checked', ''))}</td>
      <td>{_e(t('dev_passport.approved'))}: {_e(sig.get('approved', ''))}</td>
      <td>{_e(t('common.date'))}: {_e(meta.get('date', ''))}</td></tr></table>
    """
    return render(body, f"{t('dev_passport.title')} {meta.get('number', '')}")


def rings_pdf(res: dict, t: Callable[[str], str], meta: dict) -> bytes:
    lab = {"m": t("units.m")}
    parts = [f"<h1>{_e(t('ring.title'))}: {_e(meta.get('stope', ''))}</h1>"
             f"<div class='small'>{_e(meta.get('mine', ''))} · {_e(t('ring.direction'))}: "
             f"{_e(t('ring.directions.' + res['params']['direction']))} · B = {res['params']['burden']} {_e(t('units.m'))} · "
             f"E = {res['params']['toe_spacing']} {_e(t('units.m'))} · Ø {res['input'].get('hole_diameter')} {_e(t('units.mm'))} · "
             f"{_e(t('common.date'))}: {_e(meta.get('date', ''))}</div>"]
    ind = res["indicators"]
    parts.append("<table class='small'>" + "".join(
        f"<tr><td>{_e(t('ring.ind.' + k))}</td><td><b>{v}</b></td></tr>" for k, v in ind.items()) + "</table>")
    for r in res["rings"][: int(meta.get("max_rings", 6))]:
        parts.append(f"<h2>{_e(t('ring.ring'))} {r['no']} · x = {r['x']} · {r['charge_kg']} {_e(t('units.kg'))} · "
                     f"{r['tonnes']} {_e(t('units.t'))}</h2>")
        parts.append(drawing.ring_view(res, r, lab, energy=r["no"] == 1))
        rows = "".join(f"<tr><td>{h['id']}</td><td>{h['length']:.1f}</td><td>{h['angle']:.0f}</td><td>{h['uncharged']:.1f}</td>"
                       f"<td>{h['charge_kg']:.1f}</td><td>{h.get('delay_ms', '')}</td></tr>" for h in r["holes"])
        parts.append(f"<table class='small'><tr><th>№</th><th>{_e(t('dev_passport.length_m'))}</th><th>{_e(t('dev_passport.angle_deg'))}</th>"
                     f"<th>{_e(t('ring.uncharged'))}</th><th>{_e(t('dev_passport.charge'))}</th><th>{_e(t('dev_passport.delay_ms'))}</th></tr>{rows}</table>")
    return render("".join(parts), t("ring.title"))


def table_pdf(title: str, subtitle: str, sections: list[dict]) -> bytes:
    """Отчет: секции [{title, columns: [(key, label)], rows: [...], kv: [(label, value)]}]."""
    parts = [f"<h1>{_e(title)}</h1><div class='small'>{_e(subtitle)}</div>"]
    for s in sections:
        parts.append(f"<h2>{_e(s.get('title', ''))}</h2>")
        if s.get("kv"):
            parts.append("<table>" + "".join(f"<tr><td>{_e(k)}</td><td><b>{_e(v)}</b></td></tr>" for k, v in s["kv"]) + "</table>")
        if s.get("rows") is not None:
            cols = s["columns"]
            head = "".join(f"<th>{_e(lbl)}</th>" for _, lbl in cols)
            body = "".join("<tr>" + "".join(f"<td>{_e(r.get(k))}</td>" for k, _ in cols) + "</tr>" for r in s["rows"])
            parts.append(f"<table class='small'><tr>{head}</tr>{body}</table>")
    return render("".join(parts), title)
