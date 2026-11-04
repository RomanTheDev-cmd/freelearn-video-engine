"""Stage an export bundle, retain prior files, roll back ordinary write errors."""
import json
import os
import shutil
import time
from pathlib import Path


BUNDLE_SUFFIXES=['.srt','.credits.txt','.rights.txt','.render.json','.mix.wav','.mix.speech.wav','.mix.music.wav','.mix.audio.json']


def validate_output_paths(dest,inputs=()):
    dest=Path(dest)
    if dest.suffix.lower()!='.mp4':raise RuntimeError('Результат должен иметь расширение .mp4')
    if dest.parent.exists() and not dest.parent.is_dir():raise RuntimeError('Папка результата недоступна')
    targets=[dest]+[dest.with_suffix(ext) for ext in BUNDLE_SUFFIXES]
    protected={Path(p).resolve() for p in inputs}
    for path in targets:
        if path.is_symlink() or (path.exists() and not path.is_file()) or path.resolve() in protected:
            raise RuntimeError('Путь экспорта конфликтует с исходником или недоступен: '+str(path))


def validate_report_path(output,inputs=(),protected_root=None):
    if output is None:return
    output=Path(output)
    if output.suffix.lower()!='.json':raise RuntimeError('Для отчёта нужен отдельный файл .json')
    resolved=output.resolve()
    if output.is_symlink() or (output.exists() and not output.is_file()) or resolved in {Path(p).resolve() for p in inputs}:
        raise RuntimeError('Отчёт не должен перезаписывать исходные файлы')
    if protected_root is not None and (resolved==Path(protected_root).resolve() or Path(protected_root).resolve() in resolved.parents):raise RuntimeError('Отчёт должен находиться вне общего источника навыка')


def commit_bundle(pairs):
    pairs=[(Path(a),Path(b)) for a,b in pairs]
    if not pairs:raise RuntimeError('Пустой комплект экспорта')
    parents={b.parent.resolve() for _,b in pairs}
    if len(parents)!=1 or len({b.name for _,b in pairs})!=len(pairs):raise RuntimeError('Некорректные пути комплекта экспорта')
    for source,dest in pairs:
        if not source.is_file() or (dest.exists() and not dest.is_file()) or dest.is_symlink():raise RuntimeError('Недоступен файл экспорта: '+str(dest))
        if source.resolve()==dest.resolve():raise RuntimeError('Источник совпадает с результатом')
    parent=next(iter(parents));history=parent/'.freelearn-cache'/f'export-{time.time_ns()}'
    new=history/'new';previous=history/'previous';failed=history/'failed'
    for folder in (new,previous,failed):folder.mkdir(parents=True)
    manifest=history/'manifest.json';state={'status':'staging','files':[b.name for _,b in pairs]}
    def save():manifest.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    save();originals=[];written=[]
    try:
        for source,dest in pairs:
            shutil.copy2(source,new/dest.name)
            if dest.exists():shutil.copy2(dest,previous/dest.name);originals.append(dest)
        state['status']='committing';save()
        # Put the MP4 last; expose only a completed mux after its companion files.
        for _,dest in sorted(pairs,key=lambda item:item[1].suffix.lower()=='.mp4'):
            os.replace(new/dest.name,dest);written.append(dest)
        state['status']='complete';save()
    except BaseException:
        restoration=[]
        for dest in reversed(written):
            try:
                if dest in originals:
                    shutil.copy2(previous/dest.name,failed/('restore-'+dest.name));os.replace(failed/('restore-'+dest.name),dest)
                else:os.replace(dest,failed/dest.name)
            except OSError as error:restoration.append(str(error))
        state.update(status='rollback_failed' if restoration else 'rolled_back',restoration_errors=restoration)
        save()
        if restoration:raise RuntimeError('Не удалось восстановить комплект; прежние файлы сохранены в '+str(previous))
        raise
    # Previous exports are retained, never silently deleted by temporary cleanup.
    return history
