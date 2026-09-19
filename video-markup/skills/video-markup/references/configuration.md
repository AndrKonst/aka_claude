# Настройка video-markup

Плагину нужны `ffmpeg` и сборка `whisper.cpp` (`whisper-cli`) с загруженной моделью.

## Приоритет источников настроек

1. Переменные окружения: `WHISPER_CLI`, `WHISPER_MODEL`, `WHISPER_LANG`.
2. Файл `.claude/video-markup.local.md` в корне текущего проекта.
3. Встроенные дефолты.

## Файл конфигурации

Создай `.claude/video-markup.local.md` в проекте:

```markdown
---
whisper_cli: /Users/andronov_ka/my_apps/MacWhisper/build/bin/whisper-cli
whisper_model: /Users/andronov_ka/my_apps/MacWhisper/models/ggml-large-v3-turbo.bin
language: ru
---

Заметки по настройке для этого проекта (необязательно).
```

## Дефолты

| Ключ | Значение по умолчанию |
|------|------------------------|
| `whisper_cli` | `/Users/andronov_ka/my_apps/MacWhisper/build/bin/whisper-cli` |
| `whisper_model` | `/Users/andronov_ka/my_apps/MacWhisper/models/ggml-large-v3-turbo.bin` |
| `language` | `ru` |

## Установка зависимостей

```bash
brew install ffmpeg

git clone https://github.com/ggml-org/whisper.cpp
cd whisper.cpp
cmake -B build && cmake --build build -j --config Release
sh ./models/download-ggml-model.sh large-v3-turbo
```

После сборки `whisper-cli` лежит в `build/bin/whisper-cli`, модель — в `models/ggml-large-v3-turbo.bin`.

## Важно про модели

Для русской речи **нельзя** использовать англоязычные модели (`ggml-base.en.bin`, `ggml-small.en.bin` и прочие с суффиксом `.en`) — результат будет мусорным. Бери многоязычные: `large-v3-turbo`, `large-v3`, `medium`.

## Рекомендуемые разрешения

Чтобы не подтверждать каждый вызов, добавь в `.claude/settings.local.json` проекта:

```json
{
  "permissions": {
    "allow": [
      "Bash(ffmpeg:*)",
      "Bash(ffprobe:*)",
      "Bash(/Users/andronov_ka/my_apps/MacWhisper/build/bin/whisper-cli:*)"
    ]
  }
}
```
