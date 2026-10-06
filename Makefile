# UG Blast Loop (digital_mine) — команды управления
SHELL := /bin/bash
ROOT  := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

export PATH := $(HOME)/.local/bin:$(PATH)
export KUBECONFIG := $(ROOT)/.secrets/kubeconfig
export HELM_CONFIG_HOME := $(ROOT)/.cache/helm/config
export HELM_CACHE_HOME  := $(ROOT)/.cache/helm/cache
export HELM_DATA_HOME   := $(ROOT)/.cache/helm/data
# Прокси окружения для кластера и сборки не нужен
unexport HTTP_PROXY HTTPS_PROXY http_proxy https_proxy

CLUSTER ?= digital-mine
NS      ?= digital-mine
s       ?= api

.PHONY: help tools up down status demo logs test lint build import deploy backup restore

help: ## Список команд
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n",$$1,$$2}'

tools: ## Поставить утилиты в ~/.local/bin
	@bash scripts/install-tools.sh

up: ## Поднять весь стек (кластер, инфраструктура, сервисы)
	@bash scripts/up.sh

down: ## Удалить кластер и всё созданное проектом
	@bash scripts/down.sh

status: ## Что запущено и сколько памяти
	@bash scripts/status.sh

build: ## Собрать образы сервисов и загрузить в кластер
	@bash scripts/build.sh

deploy: ## Переустановить helm-релизы (без пересборки)
	@bash scripts/deploy.sh

demo: ## Запустить эмулятор со сценариями
	@bash scripts/demo.sh

logs: ## Логи сервиса: make logs s=api
	@kubectl -n $(NS) logs -l app.kubernetes.io/component=$(s) --tail=200 -f --max-log-requests 10

test: ## Все тесты (pytest, vitest, проверка чарта)
	@bash scripts/test.sh

lint: ## ruff, eslint, helm lint, kubeconform
	@bash scripts/lint.sh

backup: ## Резервная копия баз и файлов в backups/
	@bash scripts/backup.sh

restore: ## Восстановление: make restore b=backups/<папка>
	@bash scripts/restore.sh $(b)
