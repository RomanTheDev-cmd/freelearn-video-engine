# Внутренний движок «Создание видео»

## Генератор речи удалён — Роман, 2026-11-03

Qwen полностью выведен из видеопроцесса. Его модели, адаптер и отдельное окружение удалены с рабочих путей. Не восстанавливать и не использовать его как fallback. Готовые медитации и ранее принятые WAV не изменяются; одобрения/лицензии/профили сохраняют историческое происхождение записей.

Этот общий движок по-прежнему содержит проверку сценариев, компоновку, работу с сохранённой речью, сведение, экспорт и проверки. Активного нейросинтезатора для новой медитационной речи в нём больше нет: при отсутствующем WAV команда прекращается с явной причиной. Голос обучающих роликов — выбранный TeraTTSv2 ru_m1, отдельный проектный путь из `sozdanie-video/references/obuchayushchee-video.md`; это не утверждение, что `build_video.py` уже интегрирован с Tera.

Вход — единый `~/.codex/skills/sozdanie-video` / `~/.claude/skills/sozdanie-video`. Общий источник движка — эта папка iCloud; отдельныйSKILL.md и копии агентов не создавать. Окружения локально: .venv для картинки, .venv-audio дляFX, .venv-asr дляWhisper, .venv-tts-comparison дляTera. Кэш/веса не хранить вiCloud. Новое производство требует явного запроса, аудит/обслуживание его не разрешает.

# Freelearn Video — внутренний движок навыка «Создание видео»

## Одобрение Романа — 2026-10-20

Профиль синтетического образца и исторические render sidecars не переписываются: их false/hearing_reviewed=false описывают момент создания, текущее решение находится в записи одобрения и style/credits. Это сохраняет fingerprint и кэш речи. Одобрение пользователя не означает, что Codex сам прослушал аудио, и не заменяет проверку нового экспорта.

Вход для пользователя — общий навык «Создание видео» (`~/.codex/skills/sozdanie-video` или `~/.claude/skills/sozdanie-video`; до 2026-10-29 — VideoFreeLearn/`videofreelearn`). Там же правила Романа по форматам (медитация и обучающее видео — разные паттерны) и словарь произношения. Этот файл — производственные инструкции; все относительные пути ниже считаются от этой папки движка. Отдельный SKILL.md здесь не создавать: это вернёт удалённый дубль.

One skill for Claude and Codex. The only source is iCloud `Главная рабочая папка ИИ/Служебное/Общие навыки/freelearn-video`; `~/.claude/skills/freelearn-video` and `~/.codex/skills/freelearn-video` are links to it. Edit only the source, copy it to `Резервные копии одобренных работ` first, then bump `VERSION` and `CHANGELOG.md`. Claude and Codex work on this skill and the Freelearn site together: one shared journal for both, `/Users/roman/Library/Mobile Documents/com~apple~CloudDocs/Главная рабочая папка ИИ/Проекты/FreeLearn/Сайт/Журнал проекта.md`; collaboration rules are in `AGENTS.md` in that folder — read both before starting. Python environments (`.venv`, `.venv-asr`, `.venv-audio`, `.venv312`) are local to this Mac in `~/.local/share/freelearn-video` (override with `FREELEARN_VIDEO_RUNTIME`); never put them into iCloud. Model weights stay in `~/.cache/freelearn-video`.

Use for producing Russian educational videos (normally 60–120 seconds) and calm guided meditations (normally 7 minutes). Keep the author anonymous: do not use their face, real voice, cloned voice, or personal details. Production runs locally; Codex or Claude may help write and fact-check the script, but never invent a software interface or an unprovided screen recording.

## Хранение видео и экспортов — Роман, 2026-10-20

**Заменено указанием Романа 2026-10-29:** готовые видео — `Проекты/Создание видео/<название>.mp4` прямо в корне, без папок на ролик; сценарии, исходники, прежние версии, `.srt`, `.credits.txt`, `.rights.txt`, `.render.json`, кэш и отчёты — `Проекты/Создание видео/Техническое/<название>/`. Схема ниже — история; медитации 01–10 уже перенесены, сайт FreeLearn берёт их через `Сайт/media.json`. Подробно — навык «Создание видео».

Основная папка: `/Users/roman/Library/Mobile Documents/com~apple~CloudDocs/Главная рабочая папка ИИ/Проекты/FreeLearn`.

- `Экспорт/Медитация/`
- `Экспорт/Музыка/`
- `Экспорт/Шахматы/`
- `Экспорт/3Д моделирование и печать/`

Каждое итоговое видео — отдельная папка с понятным русским названием внутри своей темы; MP4 и обязательные `.srt`, `.credits.txt`, `.rights.txt`, `.render.json` имеют одинаковую основу имени и лежат рядом. В «Экспорт» помещать актуальную итоговую версию. Пробные варианты, кэш, stems, метрики, сценарии, исходники и технические отчёты хранить в `Рабочие материалы/`, отдельно от итоговых видео. Для явно заказанного производства собирать комплект в рабочей папке; после проверки переносить итоговые пять файлов в тематический экспорт, оставляя stems/кэш/метрики в рабочих материалах. При смене имени сохранять одинаковую основу у MP4 и companions и рабочие ссылки в metadata/записи одобрения.

Папка `Видео и превью` — скрытая локальная ссылка совместимости на `Рабочие материалы`; новые материалы по старому пути не создавать. Она сохраняет пути в исторических отчётах и кэше. Наличие локальных ссылок не подтверждает синхронизацию iCloud на других устройствах. Схема папок не разрешает новый рендер, синтез, публикацию или 3D-печать.

## Отдельные главы и разные треки — Роман, 2026-10-20

Каждая глава книги — самостоятельное видео со своим названием, вступлением, завершением и папкой экспорта. Главы не склеивать в один длинный ролик. В этой серии каждой главе назначать **другую композицию** через music_asset_id; другой отрывок одного произведения не считается другим треком. Проверять уникальность ISRC/источников и хешей фактических записей. Ранее принятый Tranquility остаётся у главы1. Новые музыкальные записи зарегистрированы с правами как candidate/approved_for_publication=false; прежнее одобрение голоса и Tranquility на них не распространяется. Новые записи не выдавать за прослушанные или принятые Романом. При замене только музыки сохранять обработанную speech stem без повторных FX и копировать видеопоток, затем проверять фактический новый AAC/MP4. Исходники полных записей/частичные загрузки — в локальном кэше; общие assets содержат лицензированные490секундные фрагменты без перекодирования, достаточные для450–480сек видео.

## Workflow

1. Read `references/workflow.md` and the relevant structured example in `assets/examples/`. For new videos, create one JSON file from the matching example and keep narration, on-screen text, scene order, timing, and asset IDs together.
2. Resolve factual requirements and inspect any supplied source material. Ask only for missing material needed to show a real interface or make the lesson accurate. Keep the saved Freelearn design and voice settings in `assets/style.json`; do not redesign without an explicit request.
3. Respect Roman's explicit limit preference (2026-10-15): skill maintenance and logic review do not authorize making videos or synthesizing speech. Default to code inspection and `scripts/check_logic.py`; use existing reports and exports where relevant. Render or synthesize only when the current user request explicitly calls for a video/audio sample or export. Для сохранённой ранее принятой речи сохранять её approval/provenance; новый нейросинтез отключён. Текущий учебный Tera-путь находится в sozdanie-video. An instruction to check quality alone does not authorize more renders. Keep both approval flags false while the voice remains a candidate. Only mark the voice approved after the user accepts it. Full HD is 1920×1080 for 16:9 or 1080×1920 for 9:16. The builder validates scenario types/timing before external tools and stages an export bundle before replacing files. Prior versions remain in `.freelearn-cache/export-*/previous`; ordinary transfer errors trigger rollback. Power loss/SIGKILL can interrupt the multi-file transfer, so do not promise an atomic bundle. New render/ASR reports bind to MP4 SHA-256; older exports without a hash remain explicitly unverified for that link. Reports must use separate JSON paths outside the shared skill. Run `scripts/build_video.py` and `scripts/check_video.py`; its default check enforces 16:9 Full HD. Use `--format 9:16` to check vertical Full HD, and `--preview` only for reduced previews. For meditations the widget holds the scenario stage instruction for the whole scene (caption_mode=stage); individual utterances do not switch the widget. Lessons default to caption_mode=speech. SRT and speech checks still use actual WAV timings; timing within long wrapped utterances is estimated, not phoneme-aligned.
4. Read `assets/credits.json` and include the generated `.credits.txt` with the deliverable. For Dialogs-RU voice output, also keep the `.rights.txt` sidecar with the full license and restrictions; distribution requires passing the restrictions to recipients. Reuse cached narration, images, intro/outro, and music when their input hash has not changed. Do not fetch or include an external asset until its individual rights and required attribution are recorded.

## Style and pacing

Use the one-second Freelearn intro and the site's northern design: snow/mist backgrounds, fjord blue accent, restrained rounded cards, clear typography, gentle fades, and a quiet outro. The saved light and dark palettes in assets/style.json match the site's 2026-10-14 CSS. Read references/design.md when creating or changing visual components. Select the fixed MP4 theme with scenario theme or --theme; light is the default. Every frame must include the same separate caption widget below the image area, with the site's rounded accent tile, mountain mark, and Freelearn wordmark in a persistent footer below the widget. Never place spoken captions over a landscape. Keep landscape color natural and restrained; place stills and moving footage in the same rounded window with generous margins. Final format defaults to 16:9 Full HD (1920×1080); render 9:16 Full HD (1080×1920) only when requested and only if the composition preserves important content. Keep the layout minimal and calm, with purposeful scenes and no paragraph blocks.

For meditation, use a brief introduction, occasional short prompts, long practice gaps and slow nature scenes. Keep one concise stage instruction visible in the separate widget for the whole practice stage; do not flip it at every sentence. Use gentle 0.9-second picture dissolves; widget/footer timing stays unchanged. Slow footage moderately: inspect the whole chosen source interval and prefer a longer take or a subtle animated still over extreme stretching of a short clip. Do not use frame blending on foliage/water by default. No breath holding, treatment promises or pressure to continue through discomfort.

## Voice, music and quality

For skill changes, run `scripts/check_logic.py` in `.venv` and syntax/skill validation without video or model inference. For audio input/math changes also run `scripts/check_audio_logic.py` in `.venv-audio`; it uses temporary numeric fixtures, with no synthesis, instrument or effects rendering. Its tests block external subprocesses. State explicitly that changed rendering/audio paths have not been exercised by a new export. When Roman explicitly requests a render, choose the relevant sample (for example `assets/examples/meditation-preview.json --preview --voice review`) and run `check_video.py --preview --ocr --full-decode`. Inspect actual encoded frames at cues, scene changes and the end. The video checker is strict by default: incomplete metadata or empty required credits/rights/SRT with expected speech fail. Use --legacy only for explicitly labelled historical inspection; its warnings are not a strict acceptance. Reports bind to MP4/checker hashes and reject changes during scanning. Test a lesson with music disabled only when such a render is authorized. For Full HD use the checker without `--preview`; add `--format 9:16` only when reviewing that format. `check_speech.py` runs local Russian Whisper against the actual encoded prompt intervals without an initial text prompt. A mismatch needs investigation; do not silently change the expected transcript to match a bad utterance. OCR compares the caption region without its title and preserves word order/repetitions, including repeated negations. OCR and logo checks sample frames and can give false positives; inspect uncertain results directly.

Technical measurements and exact ASR words do not establish natural diction, accent, pleasant timbre or musical quality. If audio input is unavailable, say so; Roman provides listening assessment. Keep limitations visible in the report. Only use free local production tools; no paid API, cloud quota, proprietary voice substitution or paid DAW dependency. Earlier Dialogs-RU has separate OpenRAIL restrictions documented in `workflow.md` and is not a silent fallback. eSpeak NG is for labelled technical checks only. Record individual external asset rights before downloading/using them and retain `.credits.txt`, `.rights.txt`, `.srt`, `.render.json` with every MP4.

## Cost and accuracy

Local rendering consumes this computer's CPU, storage, and time. Script preparation and review in Codex or Claude consume subscription limits. Do not promise unlimited production. Do not publish videos, deploy services, push code, or add third-party dependencies outside local production without an explicit request.

## Files

- Workflow, install notes, current blockers, and commands: `references/workflow.md`.
- Northern component templates and theme selection: `references/design.md`.
- Short launch instructions: `references/quickstart.md`.
- Visual and voice defaults: `assets/style.json`.
- Reusable media and per-asset rights: `assets/credits.json`.
- Example lesson and meditation JSON: `assets/examples/lesson.json` and `assets/examples/meditation.json`.
- Fast logic checks without rendering, synthesis or external subprocesses: `scripts/check_logic.py`; numeric/input audio checks: `scripts/check_audio_logic.py` in `.venv-audio`.
- Local scripts: `scripts/build_video.py`, `scripts/check_video.py`, `scripts/check_speech.py`, `scripts/process_audio.py`, `scripts/make_ambient.py`.
- Component contact sheets: `scripts/preview_components.py --output /path/to/review-folder` (both themes and both formats; no speech synthesis).
- Version and history: `VERSION`, `CHANGELOG.md`.

Намеренно тихий preview урока без речевых интервалов и с music_enabled=false допускается с явным measurement_status=intentional_silence и предупреждением. Неизвестный вывод измерителя либо тишина при ожидаемом звуке остаются ошибкой. Это не одобрение качества звука.
