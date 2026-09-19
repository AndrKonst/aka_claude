#!/usr/bin/env bash
# Запускает MCP-сервер интерпретатором из окружения проекта.
#
# Окружение Python живёт в проекте (<проект>/.claude/smart-flights/.venv), а не
# рядом с плагином: папка плагина лежит в общем кэше ~/.claude и пересоздаётся
# при каждом обновлении версии, унося окружение с собой.
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="${1:-}"

# ${CLAUDE_PROJECT_DIR} мог не раскрыться — тогда ориентируемся на текущую директорию.
if [ -z "$PROJECT_DIR" ] || [ "$PROJECT_DIR" = '${CLAUDE_PROJECT_DIR}' ] || [ ! -d "$PROJECT_DIR" ]; then
  PROJECT_DIR="$PWD"
fi

VENV_PYTHON="$PROJECT_DIR/.claude/smart-flights/.venv/bin/python"
PYTHON="${SMART_FLIGHTS_PYTHON:-$VENV_PYTHON}"

if [ ! -x "$PYTHON" ]; then
  cat >&2 <<MSG
smart-flights: окружение Python для этого проекта не создано.

Ожидалось: $VENV_PYTHON

Создайте его одной командой из корня проекта:
  bash "$PLUGIN_ROOT/install.sh"

Окружение ставится в сам проект, глобальная папка ~/.claude не затрагивается.
MSG
  exit 1
fi

export SMART_FLIGHTS_ROOT="$PLUGIN_ROOT"
export SMART_FLIGHTS_PROJECT_DIR="$PROJECT_DIR"
exec "$PYTHON" "$PLUGIN_ROOT/server/server.py"
