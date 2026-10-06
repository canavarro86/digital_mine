"""Генерация дашбордов Grafana (раздел 19.1) → grafana/dashboards/*.json. Запуск: python3 scripts/gen_dashboards.py"""
import json
from pathlib import Path

CH = {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"}
PG = {"type": "grafana-postgresql-datasource", "uid": "postgres"}
PR = {"type": "prometheus", "uid": "prometheus"}
LK = {"type": "loki", "uid": "loki"}
OUT = Path(__file__).resolve().parents[1] / "grafana" / "dashboards"


def ch(sql, fmt="table"):
    return {"datasource": CH, "editorType": "sql", "queryType": fmt, "format": 1 if fmt == "table" else 0, "rawSql": sql, "refId": "A"}


def pg(sql):
    return {"datasource": PG, "editorMode": "code", "format": "table", "rawSql": sql, "refId": "A", "rawQuery": True}


def prom(expr, legend=""):
    return {"datasource": PR, "expr": expr, "legendFormat": legend, "refId": "A"}


def panel(kind, title, target, x, y, w, h, unit=None, extra=None):
    p = {"type": kind, "title": title, "gridPos": {"x": x, "y": y, "w": w, "h": h}, "datasource": target["datasource"],
         "targets": [target], "fieldConfig": {"defaults": {}, "overrides": []}, "options": {}}
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    if kind == "barchart":
        p["options"] = {"xTickLabelRotation": -30, "showValue": "auto", "legend": {"showLegend": True}}
    if kind == "table":
        p["options"] = {"showHeader": True}
    if extra:
        p.update(extra)
    return p


def dash(uid, title, panels, refresh="30s", time_from="now-24h"):
    return {"uid": uid, "title": title, "tags": ["digital-mine"], "timezone": "browser", "schemaVersion": 39, "refresh": refresh,
            "time": {"from": time_from, "to": "now"}, "panels": panels, "editable": True}


D = {}
D["01-mine-online"] = dash("dm-online", "1. Рудник онлайн", [
    panel("stat", "Машины работают", pg("SELECT count(*) FILTER (WHERE status='working') AS работают, count(*) FILTER (WHERE status IN ('repair','maintenance')) AS ремонт FROM fleet"), 0, 0, 8, 4),
    panel("stat", "Забои в работе", pg("SELECT count(*) FILTER (WHERE status NOT IN ('ready','done')) AS в_цикле, count(*) FILTER (WHERE status='ready') AS готовы FROM faces"), 8, 0, 8, 4),
    panel("stat", "Открытые алерты", pg("SELECT count(*) AS открыто FROM alerts WHERE status='open'"), 16, 0, 8, 4),
    panel("table", "Статусы забоев", pg("SELECT f.name AS забой, f.kind AS вид, f.status AS статус, f.cycle_no AS цикл, to_char(f.status_since,'DD.MM HH24:MI') AS с FROM faces f ORDER BY f.kind, f.name"), 0, 4, 12, 12),
    panel("table", "Машины и люди сейчас", ch("SELECT machine AS машина, argMax(status, ts) AS статус, argMax(operator, ts) AS оператор, argMax(face, ts) AS забой, max(ts) AS последнее_событие FROM telemetry WHERE ts > now() - INTERVAL 1 DAY AND machine NOT LIKE 'LOAD-%' GROUP BY machine ORDER BY machine"), 12, 4, 12, 12),
    panel("timeseries", "Переходы статусов забоев в час", ch("SELECT toStartOfHour(ts) AS t, count() AS переходы FROM face_status WHERE $__timeFilter(ts) GROUP BY t ORDER BY t"), 0, 16, 24, 7),
])
D["02-development"] = dash("dm-dev", "2. Проходка", [
    panel("stat", "Подвигание за период, м", ch("SELECT round(sum(advance),1) AS м FROM cycles WHERE $__timeFilter(ts)"), 0, 0, 6, 4),
    panel("stat", "КИШ средний", ch("SELECT round(avg(kish),3) AS КИШ FROM cycles WHERE $__timeFilter(ts)"), 6, 0, 6, 4),
    panel("stat", "Лишняя порода, т", ch("SELECT round(sum(extra_t)) AS т FROM cycles WHERE $__timeFilter(ts)"), 12, 0, 6, 4),
    panel("stat", "Лишняя порода, USD", ch("SELECT round(sum(extra_cost)) AS USD FROM cycles WHERE $__timeFilter(ts)"), 18, 0, 6, 4, "currencyUSD"),
    panel("timeseries", "КИШ и перебор по часам", ch("SELECT toStartOfHour(ts) AS t, avg(kish) AS КИШ, avg(overbreak_pct)/100 AS перебор FROM cycles WHERE $__timeFilter(ts) GROUP BY t ORDER BY t"), 0, 4, 12, 8),
    panel("barchart", "Лишняя порода по забоям, т", ch("SELECT face AS забой, round(sum(extra_t),1) AS т FROM cycles WHERE $__timeFilter(ts) GROUP BY face ORDER BY т DESC"), 12, 4, 12, 8),
    panel("barchart", "Подвигание и КИШ по буровым", ch("SELECT machine AS буровая, round(sum(advance),1) AS подвигание, round(avg(kish),3) AS КИШ FROM cycles WHERE $__timeFilter(ts) AND machine!='' GROUP BY machine ORDER BY machine"), 0, 12, 12, 8),
    panel("piechart", "Причины отклонений", ch("SELECT cause AS причина, count() AS циклов FROM cycles WHERE $__timeFilter(ts) GROUP BY cause"), 12, 12, 12, 8),
])
D["03-drilling-accuracy"] = dash("dm-drill", "3. Точность бурения", [
    panel("barchart", "Среднее отклонение по машинам, %", ch("SELECT machine AS машина, round(avg(deviation_pct),2) AS отклонение FROM drilling WHERE $__timeFilter(ts) AND machine!='' GROUP BY machine ORDER BY machine"), 0, 0, 12, 8),
    panel("barchart", "Среднее отклонение по людям, %", ch("SELECT operator AS бурильщик, round(avg(deviation_pct),2) AS отклонение FROM drilling WHERE $__timeFilter(ts) AND operator!='' GROUP BY operator ORDER BY отклонение DESC"), 12, 0, 12, 8),
    panel("timeseries", "Отклонение Boomer и Simba по часам, %", ch("SELECT toStartOfHour(ts) AS t, avgIf(deviation_pct, machine_type='dev_drill') AS Boomer, avgIf(deviation_pct, machine_type='ring_drill') AS Simba FROM drilling WHERE $__timeFilter(ts) GROUP BY t ORDER BY t"), 0, 8, 12, 8),
    panel("stat", "Шпуры/скважины > 3 % отклонения", ch("SELECT countIf(deviation_pct>3) AS выше_3, count() AS всего FROM drilling WHERE $__timeFilter(ts)"), 12, 8, 6, 8),
    panel("stat", "Недобур, % длины", ch("SELECT round(avg((design_length-length)/design_length*100),2) AS недобур FROM drilling WHERE $__timeFilter(ts) AND design_length>0"), 18, 8, 6, 8),
])
D["04-stopes"] = dash("dm-stopes", "4. Камеры", [
    panel("stat", "Отбито, т", ch("SELECT round(sum(blasted_t)) AS т FROM stopes WHERE $__timeFilter(ts)"), 0, 0, 6, 4),
    panel("stat", "Разубоживание, %", ch("SELECT round(avg(dilution_pct),1) AS проц FROM stopes WHERE $__timeFilter(ts)"), 6, 0, 6, 4),
    panel("stat", "Потери, т", ch("SELECT round(sum(loss_t)) AS т FROM stopes WHERE $__timeFilter(ts)"), 12, 0, 6, 4),
    panel("stat", "Результат, USD", ch("SELECT round(sum(result_usd)) AS USD FROM stopes WHERE $__timeFilter(ts)"), 18, 0, 6, 4, "currencyUSD"),
    panel("barchart", "ELOS висячего и лежачего бока по камерам, м", ch("SELECT stope AS камера, round(avg(elos_hw),2) AS ELOS_ВБ, round(avg(elos_fw),2) AS ELOS_ЛБ FROM stopes WHERE $__timeFilter(ts) GROUP BY stope ORDER BY stope"), 0, 4, 12, 9),
    panel("table", "Итоги камер", ch("SELECT stope AS камера, round(blasted_t) AS отбито_т, round(dilution_pct,1) AS разуб_проц, round(loss_t) AS потери_т, round(elos_hw,2) AS ELOS_ВБ, round(result_usd) AS USD, cause AS причина FROM stopes WHERE $__timeFilter(ts) ORDER BY ts DESC"), 12, 4, 12, 9),
])
D["05-explosives"] = dash("dm-expl", "5. ВВ: план против факта", [
    panel("timeseries", "ВВ план и факт по часам, кг", ch("SELECT toStartOfHour(ts) AS t, sumIf(toFloat64OrZero(JSONExtractString(payload,'plan_kg')), type='charge') AS план, sumIf(toFloat64OrZero(JSONExtractString(payload,'fact_kg')), type='charge') AS факт FROM events WHERE $__timeFilter(ts) GROUP BY t ORDER BY t"), 0, 0, 24, 8),
    panel("barchart", "Перерасход по забоям, кг", ch("SELECT face AS забой, round(sum(explosive_fact_kg - explosive_plan_kg),1) AS перерасход FROM cycles WHERE $__timeFilter(ts) GROUP BY face ORDER BY перерасход DESC"), 0, 8, 12, 8),
    panel("stat", "Отклонение факта от плана, %", ch("SELECT round((sum(explosive_fact_kg)-sum(explosive_plan_kg))/greatest(sum(explosive_plan_kg),1)*100,1) AS проц FROM cycles WHERE $__timeFilter(ts)"), 12, 8, 6, 8),
    panel("stat", "Отказы при заряжании", ch("SELECT sum(toFloat64OrZero(JSONExtractString(payload,'misfires'))) AS отказы FROM events WHERE type='charge' AND $__timeFilter(ts)"), 18, 8, 6, 8),
])
D["06-dispatcher"] = dash("dm-dispatch", "6. Диспетчер", [
    panel("barchart", "Загрузка машин: доля времени в работе, %", ch("SELECT machine AS машина, round(countIf(status='working')/count()*100,1) AS работа FROM telemetry WHERE $__timeFilter(ts) AND machine NOT LIKE 'LOAD-%' GROUP BY machine ORDER BY machine"), 0, 0, 12, 8),
    panel("barchart", "Простои: доля idle, %", ch("SELECT machine AS машина, round(countIf(status='idle')/count()*100,1) AS простой FROM telemetry WHERE $__timeFilter(ts) AND machine NOT LIKE 'LOAD-%' GROUP BY machine ORDER BY простой DESC"), 12, 0, 12, 8),
    panel("table", "Перестановки", ch("SELECT ts AS время, kind AS вид, machine AS машина, person AS человек, face AS забой, detail AS изменение FROM dispatch WHERE $__timeFilter(ts) ORDER BY ts DESC LIMIT 100"), 0, 8, 16, 10),
    panel("stat", "Готовые забои сейчас", pg("SELECT count(*) AS готовы FROM faces WHERE status='ready'"), 16, 8, 8, 5),
    panel("table", "Открытые алерты диспетчера", pg("SELECT to_char(ts,'DD.MM HH24:MI') AS время, rule AS правило, entity AS объект FROM alerts WHERE audience='dispatcher' AND status='open' ORDER BY ts DESC"), 16, 13, 8, 5),
])
D["07-ai"] = dash("dm-ai", "7. ИИ", [
    panel("stat", "Запросов", ch("SELECT count() AS запросов, countIf(cache_hit=1) AS из_кэша FROM ai WHERE $__timeFilter(ts)"), 0, 0, 8, 5),
    panel("stat", "Токены", ch("SELECT sum(tokens_in) AS вход, sum(tokens_out) AS выход FROM ai WHERE $__timeFilter(ts)"), 8, 0, 8, 5),
    panel("stat", "Затраты, $", ch("SELECT round(sum(cost),4) AS USD FROM ai WHERE $__timeFilter(ts)"), 16, 0, 8, 5, "currencyUSD"),
    panel("barchart", "Запросы по модулям", ch("SELECT module AS модуль, count() AS запросов FROM ai WHERE $__timeFilter(ts) GROUP BY module"), 0, 5, 12, 8),
    panel("table", "Журнал", pg("SELECT to_char(ts,'DD.MM HH24:MI') AS время, username AS кто, module AS модуль, provider AS провайдер, model AS модель, tokens_in, tokens_out, round(cost::numeric,4) AS usd, cache_hit AS кэш FROM ai_requests ORDER BY id DESC LIMIT 50"), 12, 5, 12, 8),
], time_from="now-7d")
D["09-logs"] = dash("dm-logs", "9. Логи", [
    panel("logs", "Логи сервисов digital-mine", {"datasource": LK, "expr": '{namespace="digital-mine"}', "refId": "A"}, 0, 0, 24, 14),
    panel("timeseries", "Ошибки в логах (WARNING/ERROR) в минуту", {"datasource": LK, "expr": 'sum by (app_kubernetes_io_component) (count_over_time({namespace="digital-mine"} |~ "\\"level\\": \\"(WARNING|ERROR)\\"" [1m]))', "refId": "A"}, 0, 14, 24, 8),
], refresh="1m", time_from="now-1h")
for name, d in D.items():
    (OUT / f"{name}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
# дашборд платформы дополняется задержкой и HPA (файл 08-platform.json пишется вручную)
print(sorted(p.name for p in OUT.glob("*.json")))
