#!/usr/bin/env python3
"""Read-only installation inventory; no model load, downloads or sound claims."""
import argparse,hashlib,json,os,shutil,subprocess
from pathlib import Path
import sys
sys.dont_write_bytecode=True
from export_files import validate_report_path
from music_source import select_music
ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path);args=ap.parse_args();runtime=Path(os.environ.get('FREELEARN_VIDEO_RUNTIME',Path.home()/'.local/share/freelearn-video'));errors=[];versions={}
    validate_report_path(args.output,protected_root=ROOT)
    if args.output:args.output.write_text(json.dumps({'status':'incomplete','errors':['Проверка ещё не завершена']},ensure_ascii=False)+'\n')
    packages={'.venv':['pillow','pyyaml'],'.venv-asr':['mlx-whisper','soundfile'],'.venv-audio':['pedalboard','mido','soundfile','scipy','pyloudnorm']}
    for environment,names in packages.items():
        exe=runtime/environment/'bin/python'
        if not exe.exists():errors.append('Нет окружения '+str(exe));continue
        code='import importlib.metadata as m,json;print(json.dumps({n:m.version(n) for n in '+repr(names)+'}))'
        result=subprocess.run([str(exe),'-c',code],capture_output=True,text=True)
        if result.returncode:errors.append(environment+': '+result.stderr[-300:])
        else:versions[environment]=json.loads(result.stdout)
    style=json.loads((ROOT/'assets/style.json').read_text());profile=ROOT/style['voice']['reference_profile'];d=json.loads(profile.read_text());audio=profile.parent/d['audio_file']
    if hashlib.sha256(audio.read_bytes()).hexdigest()!=d['sha256'] or d.get('synthetic') is not True or d.get('recording_of_person') is not False:errors.append('Неверный синтетический voice profile')
    paths=[Path.home()/'.cache/freelearn-video/tessdata/rus.traineddata']
    try:
        registry=json.loads((ROOT/'assets/credits.json').read_text())
        select_music({'music':True},style,{a['id']:a for a in registry['assets']},ROOT)
    except RuntimeError as error:errors.append(str(error))
    for path in paths:
        if not path.exists():errors.append('Нет '+str(path))
    for name in ['ffmpeg','ffprobe','tesseract']:
        exe=shutil.which(name)
        if not exe:errors.append('Нет '+name)
        else:
            result=subprocess.run([exe,'--version' if name=='tesseract' else '-version'],capture_output=True,text=True);versions[name]=(result.stdout or result.stderr).splitlines()[0]
    links={str(Path.home()/f'.{agent}/skills/freelearn-video'):(Path.home()/f'.{agent}/skills/freelearn-video').resolve()==ROOT for agent in ['codex','claude']}
    if not all(links.values()):errors.append('Ссылки агентов расходятся')
    report={'status':'complete','skill_version':(ROOT/'VERSION').read_text().strip(),'shared_source':str(ROOT),'agent_links':links,'runtime':str(runtime),'versions':versions,'profile_sha256':d['sha256'],'voice_approved':style['voice']['approved_for_publication'],'speech_generation_available':bool(style['voice'].get('approved_command')),'optional_legacy_surge_present':(runtime/'surge-xt-1.3.4/Surge XT.vst3').exists(),'errors':errors,'not_checked':['Neural model inference','Plugin rendering','New meditation speech generation is disabled; preserved reference approval is historical','Listening quality']}
    data=json.dumps(report,ensure_ascii=False,indent=2)+'\n';print(data)
    if args.output:args.output.write_text(data)
    return 1 if errors else 0
if __name__=='__main__':raise SystemExit(main())
