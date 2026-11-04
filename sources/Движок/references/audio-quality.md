> 2026-11-03 — (Codex): прежний генератор речи удалён по указанию Романа. Сохранённые записи и права остаются; автоматически восстанавливать прежние модели/окружение нельзя. Текущий учебный Tera — в sozdanie-video, Whisper — в .venv-asr. Новый медитационный нейросинтез отключён.

# Текущее одобрение

## Одобрение Романа — 2026-10-20

Одобрение2026-10-20 относится к сохранённым голосовым записям и музыке Tranquility. Профиль/запись принятия остаются историческими данными; после удаления генератора они не разрешают новый синтез.

Профиль синтетического образца и исторические render sidecars не переписываются: их false/hearing_reviewed=false описывают момент создания, текущее решение находится в записи одобрения и style/credits. Это сохраняет fingerprint и кэш речи. Одобрение пользователя не означает, что Codex сам прослушал аудио, и не заменяет проверку нового экспорта.

# Local audio and quality review (1.3)

## Installed stack and provenance

All synthesis, music, effects, OCR and exports run locally. Model downloads need internet once. Python environments stay outside iCloud; this shared source and the small synthetic voice profile are common to Claude/Codex. No paid API or paid DAW is required. Codex/Claude subscription use and local computation still consume resources.

- Python 3.12 `.venv-asr`: MLX-Whisper0.4.3 и SoundFile; пакет синтеза удалён.
- `.venv-audio`: Pedalboard 0.9.26 (GPL-3.0), Mido 1.3.3 (MIT), SoundFile 0.14.0 (BSD), SciPy 1.18.1 (BSD), pyloudnorm 0.2.0 (MIT).
- Surge XT 1.3.4 universal VST3 (GPL-3.0 software). [Official FAQ](https://surge-synthesizer.github.io/faq/) permits commercial use/distribution of generated audio. Only locally authored notes/patch settings are used; no external song/sample recording.
- Tesseract 5.5.3 plus [tessdata_fast Russian model](https://github.com/tesseract-ocr/tessdata_fast/blob/main/rus.traineddata) (Apache-2.0) in `~/.cache/freelearn-video/tessdata`. OCR is a frame check, not an audio check.

Each local model has `freelearn-provenance.json`. LFS files were verified against SHA-256 from repository metadata. `build_video.py` fingerprints actual model/config content and adapter/profile bytes before reusing speech. Do not run heavy synthesis and video rendering simultaneously on this 16 GB Mac.

## Restoring the local setup

Use Python 3.12; never create an environment under the shared skill source:

```sh
python3.12 -m venv ~/.local/share/freelearn-video/.venv-audio
~/.local/share/freelearn-video/.venv-audio/bin/python -m pip install pedalboard==0.9.26 mido==1.3.3 soundfile==0.14.0 scipy==1.18.1 pyloudnorm==0.2.0
```

Download the [official Surge plugins ZIP](https://github.com/surge-synthesizer/releases-xt/releases/download/1.3.4/surge-xt-macos-1.3.4-pluginsonly.zip); SHA-256 of the installed archive: `37d8d809693adc86587b7bc75a2384fc4e905f259aa9b9a21777749d36fbf8aa`. Extract into `~/.local/share/freelearn-video/surge-xt-1.3.4/`, leaving `Surge XT.vst3` directly inside. No administrator installation is needed. Verify archive integrity and signature before loading. The plugin-only package works for the explicitly configured Classic/Sine patches; this workflow does not require factory preset data.

Homebrew Tesseract includes eng/osd, not Russian. Download `rus.traineddata` from the official repository into the local tessdata directory; the checker passes that directory explicitly. Keep model/source revision and hashes in installation records. `doctor.py` checks paths/versions/profile integrity without loading the neural model or claiming the setup produces good sound.

## Russian synthetic voice

`assets/voices/synthetic-ru-male-v2.json` identifies a VoiceDesign-generated WAV, its transcript, source revision and SHA-256. It is **not a recording of a person**. Base uses only this synthetic reference to stabilize identity between sentences/videos. Changing it is a new voice candidate and invalidates cache. `qwen_tts.py` refuses an unverified/non-synthetic reference profile.

Current candidate uses an 11.12-second clean native reference (no tempo/FX), with all its words matched by Whisper-small. Candidate v1 and discarded longer references remain recorded for comparison. Current candidate: low/mid male Russian description; Base language explicitly Russian, seed 17, temperature .65, length scale 1.0 without an atempo filter. Roman rejected the 1.55 stretched delivery on 2026-10-18; do not restore that default merely to make the video slower. The service instruction stored in English describes timbre; spoken text is Russian. Native reference delivery is already slow. Leave 2.8 seconds between meditation sentences and long practice gaps; do not fill them with narration. Timings come from actual WAV length, never trimming speech to fit a scene. Longer wrapped captions still have estimated sub-line timing.

Do not call the candidate approved, accent-free or natural based on ASR. In initial tests standalone VoiceDesign altered a short prompt according to ASR, and Base's long intro was transcribed with «устроитесь» instead of «устройтесь». These were not accepted as exact narration. Check the final encoded phrases again after any text/voice adjustment. Do not tune only to obtain a convenient ASR result; keep meaning and disclose uncertainty.

## Music and mix

The current accepted music is **Tranquility — Kevin MacLeod**, ISRC USUAN1100581, the official recording under CC BY 4.0. `assets/credits.json` records the file/hash, author, source, terms and attribution; `audio.music_asset_id` selects it by default, and a scenario may set `music_asset_id` explicitly. Candidate status is not listening approval. `music_source.py` rejects missing/unknown/rejected sources, incomplete rights and hash mismatches before synthesis. It checks the audio stream/source duration, prepares one continuous excerpt with an 8-second fade-in/15-second fade-out (bounded for short previews), and refuses loops or silence padding. The actual selected source/edits are retained in credits/rights/render metadata.

The earlier `make_ambient.py` held-pad was rejected by Roman on 2026-10-20. Its code/MIDI remain historical technical material; it is not the default or a hidden fallback. No binaural/healing-frequency claims.

`process_audio.py` treats speech even when music is off: 70 Hz high pass, restrained 2.8 kHz cut, 8.5 kHz low pass, gentle compression and light stereo Freeverb. It preserves prompt gaps; reverb tails enter those gaps. Input narration is 24 kHz, mixed once at 48 kHz stereo. Candidate targets: active/gated speech −30.5 LUFS in meditation (−22 lesson), music −29 LUFS (−35 lesson), final transparent peak guard −2 dBFS (attenuation only, no automatic makeup). These are provisional measured targets, not a listening approval. Measure encoded AAC true peak separately.

Beside an MP4, retain `.mix.wav`, `.mix.speech.wav`, `.mix.music.wav`, `.mix.audio.json`. The JSON records actual loudness/sample peaks and whether music was enabled. Long silence is intentional; do not normalize the whole meditation to a loud streaming target. Music receives a planned 2 dB reduction for meditation (meditation_prompt_music_reduction_db) and 6 dB for lessons around actual prompt groups, with 1.8-second approach/3.5-second recovery; nearby sentences merge into one group. The voice stays quiet while the full ambient level returns during practice gaps. This is not a fast amplitude-following effect. Check speech/music separately and inspect the encoded mix with `check_speech.py` and `check_video.py --full-decode`.

## Visual and technical review

Picture-only dissolves extend the outgoing last frame as a short handle; incoming scene/audio start times do not move. The original caption widget/footer is overlaid on the blended picture, so text never doubles. Source clips fully decode before use; every encoded segment and final timeline must have the expected frame count. Stills move by a subtle 2.5% zoom across the entire scene, continuous across caption updates. No linear frame blending or extreme slowing should be assumed visually acceptable.

Run the checker with `--ocr --full-decode --output report.json`. Strict metadata and nonempty credits/rights plus SRT when speech is expected are required. The report stores MP4/checker hashes and confirms the input remained unchanged. `--legacy` permits incomplete old metadata with explicit warnings and does not certify a new export. It checks Full HD dimensions, stream lengths, frames, expected sidecars, separate picture statistics, sampled footer similarity, Russian widget OCR, AAC true peak and full decode. It samples cue/scene/transition/end frames; this does not prove the logo is present on every single frame or that all motion looks good. Inspect a contact sheet and selected transitions directly. OCR failures can reflect recognition errors; investigate instead of weakening the check silently.

Run `check_speech.py VIDEO --output asr.json` in `.venv-asr`. It uses actual encoded narration intervals, Russian Whisper-small, no initial prompt. Keep results and report mismatches. ASR match does not establish correct stress, timbre, accent or pleasantness. Determine listening access from the actual current session. If audio input is unavailable or listening was not performed, report that limitation; do not infer a permanent inability of either agent from an earlier session.

Roman first requested lower speech (2026-10-18), then a small +1.5 dB increase for clarity (2026-10-20). The current meditation candidate target is −30.5 LUFS, music dips by 2 dB. Roman accepted the current voice, music and balance on 2026-10-20; see ../assets/approvals/current-audio.json.

For remixing, `process_audio.py --speech existing.mix.speech.wav --speech-processed --music prepared-music.wav --timings timings.json ...` reuses a processed speech stem without applying EQ/reverb twice. The --speech-processed flag preserves the supplied stem level; changing the style target alone does not lower an existing processed stem. Apply the intended gain explicitly to that stem before reuse and record it. Processed samples outside PCM full scale (absolute value >1) are rejected before resampling/effects/output; valid gain is preserved. This prevents silently clipping retained PCM_24 speech stems. Use the prepared un-ducked music segment as music input; do not feed an already ducked music stem into repeated remixes. Mux video with codec copy and repeat ASR/checker on the resulting AAC.

## Additional recognizer for uncertain results

For ambiguous small-ASR results, keep its report and use the separately installed local `~/.cache/freelearn-video/whisper-large-v3-turbo` via `check_speech.py --model <that directory>`. It is the FP16 MLX conversion `mlx-community/whisper-large-v3-turbo`, pinned to `a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb`; downloaded weight file is 1,613,977,612 bytes, its LFS SHA-256 was verified and stored in local provenance. The upstream Whisper model/code is MIT. Не загружать одновременно несколько тяжёлых моделей на этом Mac. Two recognizers agreeing still do not establish correct stress or timbre, and a larger language model can smooth over a pronunciation defect. Preserve disagreement and disclose it.

For Base, `style.voice.instruct` is retained for CLI compatibility; Base generation uses the saved reference audio/transcript, not an instruction prompt. The reference profile's `instruction` records the actual VoiceDesign description used to create that profile.

Lessons split full sentences into separate WAVs with a 0.6-second gap, so actual sentence lengths control captions. For ASR, contiguous caption chunks from one long utterance are recognized together; estimated wrapped-line boundaries must not cut a word in half during checking. Meditation sentence gaps remain 2.8 seconds. Removed legacy gain/FFmpeg-EQ fields are no longer active controls; current audio targets are LUFS and prompt_music_reduction_db, effects are defined in process_audio.py.

Very slow still-photo zooms use 4× internal supersampling before returning to the delivery window. This reduces integer crop steps; it does not add source detail or increase export resolution. Real footage is not interpolated with frame blending.

Delivery render/audio sidecars use portable profile identifiers and stem basenames; never expose the author’s local home path through exported settings. Local diagnostic reports may contain workspace paths and are not publication assets.

## Logic audit 1.3.3 (no new render)

Maintenance uses check_logic.py and check_audio_logic.py; no video, voice, instrument or effects render is implied. Numeric audio fixtures are not a listening assessment. Scenario schema and proven cache timing errors are checked before expensive work. PCM reuse checks format, nonzero content and completeness; ambient must match the narration timeline. Music is never silently padded to hide missing duration. Prompt intervals are sorted/merged and must begin before the audio ends.

New export files are staged, and ordinary write failures restore prior files. Prior bundles remain under .freelearn-cache/export-*/previous, with a manifest; this is a multi-file operation, not a power-failure-proof transaction. A hard kill may require recovery from that folder. MP4 SHA-256 links new render/ASR reports; older sidecars are not retroactively rewritten. Separate report paths cannot overwrite inputs, companions or skill source. An interrupted check leaves an incomplete status, not an old success.

The MIDI arrangement is fixed. The ambient seed now controls only the slow gain drift. It does not control Surge's free-running oscillator phase or the fixed voicing; do not promise sample-exact reproduction.

Намеренно тихий preview урока без речевых интервалов и с music_enabled=false допускается с явным measurement_status=intentional_silence и предупреждением. Неизвестный вывод измерителя либо тишина при ожидаемом звуке остаются ошибкой. Это не одобрение качества звука.