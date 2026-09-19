# video-markup

Плагин Claude Code: получение таймкодов (оглавления) по видео.

Пайплайн: видео → `ffmpeg` (WAV 16 kHz mono) → `whisper-cli` (whisper.cpp) → `.vtt` → смысловая разбивка на темы с таймкодами.

## Состав

| Компонент | Тип | Назначение |
|-----------|-----|------------|
| `video-markup` | скилл | Полный путь «видео → таймкоды»; автосрабатывает на фразах вида «обработай видео», «разметь видео», «таймкоды по видео» |
| `video-transcribe` | субагент | Конвертация в WAV и транскрибация в `.vtt` |
| `/video-markup:timecodes` | команда | Явный запуск пайплайна с указанием пути |

## Использование

```
/video-markup:timecodes ~/Movies/lecture.mp4     # видео → .vtt → таймкоды
/video-markup:timecodes ~/Movies/lecture.vtt     # только таймкоды
/video-markup:timecodes                          # ищет файл в текущей директории
```

Либо просто: «обработай видео», «получить оглавление по видео» — скилл сработает сам.

Частичные сценарии:
- «только транскрибируй» → будет создан только `.vtt`;
- «только оглавление» при готовом `.vtt` → транскрибация пропускается.

## Файлы на выходе

Кладутся рядом с исходным видео, имена берутся от него:

```
lecture.mp4  →  lecture.wav   (промежуточный, 16 kHz mono)
                lecture.vtt   (транскрибация)
```

Одноимённые `.wav`/`.vtt` перезаписываются.

## Требования

- `ffmpeg` в `PATH`;
- собранный `whisper-cli` из [whisper.cpp](https://github.com/ggml-org/whisper.cpp);
- многоязычная модель (по умолчанию `ggml-large-v3-turbo.bin`).

Модели с суффиксом `.en` для русской речи непригодны.

## Настройка

Пути и язык — через `.claude/video-markup.local.md` в проекте или переменные окружения `WHISPER_CLI`, `WHISPER_MODEL`, `WHISPER_LANG`.

```markdown
---
whisper_cli: /path/to/whisper.cpp/build/bin/whisper-cli
whisper_model: /path/to/whisper.cpp/models/ggml-large-v3-turbo.bin
language: ru
---
```

Подробности — в `skills/video-markup/references/configuration.md`.
