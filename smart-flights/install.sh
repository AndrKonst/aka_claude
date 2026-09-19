#!/usr/bin/env bash
# Создаёт окружение Python для smart-flights внутри проекта.
#
# Окружение ставится в <проект>/.claude/smart-flights/.venv, а не рядом с плагином:
# папка плагина лежит в общем кэше ~/.claude и пересоздаётся при обновлении версии.
# Глобальные настройки скрипт не трогает.
#
# Использование:
#   bash install.sh                 # окружение для текущего проекта
#   bash install.sh --project PATH  # окружение для указанного проекта
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$PWD"

while [ $# -gt 0 ]; do
  case "$1" in
    --project)
      [ $# -ge 2 ] || { echo "--project требует путь" >&2; exit 1; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Неизвестный аргумент: $1" >&2
      exit 1
      ;;
  esac
done

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Директория не найдена: $PROJECT_DIR" >&2
  exit 1
fi
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"

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

TARGET="$PROJECT_DIR/.claude/smart-flights"
VENV="$TARGET/.venv"

echo "Проект:    $PROJECT_DIR"
echo "Окружение: $VENV"
echo

mkdir -p "$TARGET"

# Папка игнорирует сама себя — чужой .gitignore проекта трогать не нужно.
if [ ! -f "$TARGET/.gitignore" ]; then
  printf '*\n' > "$TARGET/.gitignore"
fi

"$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$PLUGIN_DIR/requirements.txt"

echo "Проверяю установку"
"$VENV/bin/python" -c "import fast_flights, fli, mcp, httpx" || {
  echo "Зависимости установились не полностью." >&2
  exit 1
}

cat <<MSG

Готово. Окружение стоит в проекте, глобальная папка ~/.claude не затронута.

Дальше:
  1. Включите плагин только для этого проекта, чтобы MCP-сервер не висел везде:
       /plugin install smart-flights@aka_claude
     и выберите область "local" (только вы) или "project" (вся команда через git).
  2. Перезапустите Claude Code.

Токен Aviasales (необязательно, добавляет второй источник цен):
  export AVIASALES_API_TOKEN=ваш_токен
MSG
