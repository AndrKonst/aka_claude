#!/usr/bin/env bash
# Создаёт виртуальное окружение плагина и ставит зависимости.
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$PLUGIN_DIR/.venv"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Не найден python3. Установите Python 3.11 или новее." >&2
  exit 1
fi

VERSION="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
REQUIRED="3.11"
if [ "$(printf '%s\n%s\n' "$REQUIRED" "$VERSION" | sort -V | head -1)" != "$REQUIRED" ]; then
  echo "Нужен Python $REQUIRED или новее, найден $VERSION." >&2
  exit 1
fi

echo "Создаю окружение в $VENV"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$PLUGIN_DIR/requirements.txt"

echo "Проверяю установку"
"$VENV/bin/python" -c "import fast_flights, fli, mcp, httpx" || {
  echo "Зависимости установились не полностью." >&2
  exit 1
}

echo
echo "Готово. Перезапустите Claude Code, чтобы MCP-сервер smart-flights подключился."
echo "Токен Aviasales (необязательно, добавляет второй источник цен):"
echo "  export AVIASALES_API_TOKEN=ваш_токен"
