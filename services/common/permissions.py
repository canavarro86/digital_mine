"""Права и встроенные роли . Администратор может создавать новые роли из этого списка прав."""
from __future__ import annotations

PERMISSIONS = [
    "users.manage", "system.settings", "mine.settings",
    "workings.view", "workings.edit", "geology.view", "geology.edit", "explosives.view", "explosives.edit",
    "passports.view", "passports.edit", "passports.approve", "recalc.edit",
    "fleet.view", "fleet.edit", "staff.view", "staff.edit",
    "dispatch.view", "dispatch.edit", "workflow.transition", "workflow.blast",
    "alerts.dispatch.view", "alerts.dispatch.act", "alerts.engineer.view", "alerts.admin.view",
    "reports.view", "ai.use", "console.use",
]

ENGINEER = [
    "mine.settings", "workings.view", "workings.edit", "geology.view", "geology.edit", "explosives.view",
    "explosives.edit", "passports.view", "passports.edit", "passports.approve", "recalc.edit", "fleet.view",
    "fleet.edit", "staff.view", "staff.edit", "dispatch.view", "workflow.transition", "workflow.blast",
    "alerts.dispatch.view", "alerts.engineer.view", "reports.view", "ai.use",
]
DISPATCHER = [
    "workings.view", "geology.view", "explosives.view", "passports.view", "fleet.view", "staff.view",
    "dispatch.view", "dispatch.edit", "workflow.transition", "workflow.blast", "alerts.dispatch.view",
    "alerts.dispatch.act", "reports.view",
]

BUILTIN_ROLES = {
    "admin": {"title": {"ru": "Администратор", "en": "Administrator", "es": "Administrador"},
              "permissions": PERMISSIONS, "grafana_role": "Admin"},
    "engineer": {"title": {"ru": "Инженер", "en": "Engineer", "es": "Ingeniero"},
                 "permissions": ENGINEER, "grafana_role": "Editor"},
    "dispatcher": {"title": {"ru": "Диспетчер", "en": "Dispatcher", "es": "Despachador"},
                   "permissions": DISPATCHER, "grafana_role": "Viewer"},
}

DEMO_USERS = [
    {"username": "admin", "password": "as", "role": "admin", "full_name": "Администратор системы", "lang": "ru"},
    {"username": "engineer", "password": "en", "role": "engineer", "full_name": "Инженер БВР", "lang": "ru"},
    {"username": "dispatcher", "password": "ds", "role": "dispatcher", "full_name": "Диспетчер рудника", "lang": "ru"},
]

# Рабочий процесс забоя: переходы и требуемое право
DEV_FLOW = ["ready", "drilling", "drilled", "recalculated", "handed", "accepted", "charged", "blasted",
            "ventilation", "mucking", "scaling", "support", "surveyed", "analyzed"]
STOPE_FLOW = ["ready", "drilling", "drilled", "recalculated", "handed", "accepted", "charged", "blasted",
              "draw", "cms", "analyzed"]
TRANSITION_PERM = {
    "drilling": "workflow.transition", "drilled": "workflow.transition", "recalculated": "recalc.edit",
    "handed": "recalc.edit", "accepted": "workflow.blast", "charged": "workflow.blast", "blasted": "workflow.blast",
    "wait_blast": "workflow.blast",
    "ventilation": "workflow.transition", "mucking": "workflow.transition", "scaling": "workflow.transition",
    "support": "workflow.transition", "surveyed": "workflow.transition", "draw": "workflow.transition",
    "cms": "workflow.transition", "analyzed": "recalc.edit", "ready": "workflow.transition",
    "correction": "recalc.edit",
}
