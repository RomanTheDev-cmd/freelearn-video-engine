"""Select a licensed recording before synthesis; prepare one unlooped PCM segment."""
import hashlib,json,math,re,subprocess
from pathlib import Path
from pcm_cache import validate_pcm


def file_hash(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def select_music(data,style,assets,root):
    if not data['music']:return None
    identity=data.get('music_asset_id',style['audio'].get('music_asset_id'))
    if not isinstance(identity,str) or not identity.strip():raise RuntimeError('Выберите зарегистрированный music_asset_id до сборки')
    asset=assets.get(identity)
    if not asset:raise RuntimeError('Неизвестный музыкальный ресурс: '+identity)
    if asset.get('status')=='rejected':raise RuntimeError('Музыкальный ресурс отклонён: '+identity)
    if asset.get('media_type')!='audio':raise RuntimeError('music_asset_id должен указывать на аудиозапись')
    for name in ['title','author','source','license','license_url','attribution','file']:
        if not isinstance(asset.get(name),str) or not asset[name].strip():raise RuntimeError('Нет музыкальных прав/атрибуции: '+name)
    expected=asset.get('sha256')
    if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):raise RuntimeError('Нет проверенного SHA-256 музыкальной записи')
    path=(root/asset['file']).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():raise RuntimeError('Не найден разрешённый музыкальный файл: '+identity)
    if file_hash(path)!=expected:raise RuntimeError('Музыкальный файл не соответствует зарегистрированному SHA-256')
    return {'asset_id':identity,'asset':dict(asset),'path':path,'sha256':expected}


def validate_duration(plan,duration,binary):
    if plan is None:return
    result=subprocess.run([binary('ffprobe'),'-v','error','-select_streams','a:0','-show_entries','stream=duration:format=duration','-of','json',str(plan['path'])],capture_output=True,text=True,check=True)
    data=json.loads(result.stdout)
    if not data.get('streams'):raise RuntimeError('В музыкальном источнике нет аудиопотока')
    value=data['streams'][0].get('duration')
    if value in (None,'N/A',''):value=data.get('format',{}).get('duration',0)
    length=float(value)
    if not math.isfinite(length) or length<duration-.001:raise RuntimeError('Музыкальный источник короче ролика; зацикливание и дополнение тишиной отключены')
    plan['source_duration_seconds']=length


def segment_settings(duration):
    return {'duration_seconds':duration,'fade_in_seconds':min(8,duration/2),'fade_out_seconds':min(15,duration/2)}


def prepare_music(plan,duration,cache,run,binary):
    if file_hash(plan['path'])!=plan['sha256']:raise RuntimeError('Музыкальный файл изменился после выбора')
    settings=segment_settings(duration)
    identity={'source_sha256':plan['sha256'],'preparer_sha256':file_hash(Path(__file__)),'sample_rate':48000,**settings}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:20]
    output=cache/f'music-{key}.wav'
    if not validate_pcm(output,48000,2,3,duration):
        fade_in=settings['fade_in_seconds'];fade_out=settings['fade_out_seconds']
        filters=f'afade=t=in:st=0:d={fade_in}:curve=hsin,afade=t=out:st={duration-fade_out}:d={fade_out}:curve=hsin'
        run([binary('ffmpeg'),'-v','error','-xerror','-y','-i',plan['path'],'-map','0:a:0','-t',f'{duration:.8f}','-af',filters,'-ar','48000','-ac','2','-c:a','pcm_s24le',output])
        if not validate_pcm(output,48000,2,3,duration):raise RuntimeError('Не подготовлен музыкальный PCM нужной длительности')
    return output


def metadata(plan,duration):
    if plan is None:return None
    result={name:plan['asset'].get(name) for name in ['title','author','source','license','license_url','attribution','status']}
    return {**result,'asset_id':plan['asset_id'],'sha256':plan['sha256'],'source_duration_seconds':plan['source_duration_seconds'],'excerpt_start_seconds':0,**segment_settings(duration)}
