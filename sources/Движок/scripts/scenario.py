"""Cheap scenario validation before any decoder, synthesis or export side effect."""
import copy
import math


def number(value,name,minimum=0,positive=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise RuntimeError(f'{name}: нужно конечное число')
    try:value=float(value)
    except OverflowError:raise RuntimeError(f'{name}: число слишком велико') from None
    if not math.isfinite(value):raise RuntimeError(f'{name}: нужно конечное число')
    if value<minimum or (positive and value==minimum):raise RuntimeError(f'{name}: число вне допустимого диапазона')
    return float(value)


def validate_scenario(data,voice,style,preview=False):
    if not isinstance(data,dict):raise RuntimeError('Корень сценария должен быть объектом JSON')
    data=copy.deepcopy(data)
    if data.get('type') not in ('lesson','meditation'):raise RuntimeError('type должен быть lesson или meditation')
    if voice not in ('review','approved','espeak-ng'):raise RuntimeError('Неизвестный режим голоса')
    data.setdefault('caption_mode','stage' if data['type']=='meditation' else 'speech')
    if data['caption_mode'] not in ('stage','speech'):raise RuntimeError('caption_mode должен быть stage или speech')
    fmt=data.get('format','16:9')
    if not isinstance(fmt,str) or fmt not in style['canvas']:raise RuntimeError('format должен быть 16:9 или 9:16')
    data['format']=fmt
    if 'theme' in data and (not isinstance(data['theme'],str) or data['theme'] not in style['themes']):raise RuntimeError('theme должен быть light или dark')
    for field in ('music','approved_voice'):
        if field in data and not isinstance(data[field],bool):raise RuntimeError(field+' должен быть true или false')
    data.setdefault('music',data['type']=='meditation')
    if 'music_asset_id' in data:
        if not isinstance(data['music_asset_id'],str) or not data['music_asset_id'].strip():raise RuntimeError('music_asset_id должен быть непустой строкой')
        if not data['music']:raise RuntimeError('music_asset_id нельзя игнорировать при music=false')
    if data['type']=='meditation' and not data['music']:raise RuntimeError('Для медитации ambient обязателен')
    target=number(data.get('target_duration_seconds'),'target_duration_seconds',positive=True)
    if data['type']=='lesson' and not 60<=target<=120:raise RuntimeError('Уроки Freelearn должны занимать 60–120 секунд')
    if data['music'] and not 5<=target<=3600:raise RuntimeError('Фоновый звук поддерживает ролики 5–3600 секунд')
    if preview and target<5:raise RuntimeError('Сценарий слишком короткий для предпросмотра')
    scenes=data.get('scenes')
    if not isinstance(scenes,list) or len(scenes)<2 or any(not isinstance(s,dict) for s in scenes):raise RuntimeError('scenes: нужен список сцен с intro и outro')
    if scenes[0].get('kind')!='intro' or scenes[-1].get('kind')!='outro':raise RuntimeError('В начале нужен intro, в конце — outro')
    fps=15 if preview else style['fps'];elapsed=0;last_frame=0
    for i,scene in enumerate(scenes,1):
        if scene.get('kind') not in ('intro','outro','card','nature'):raise RuntimeError(f'Сцена {i}: неизвестный kind')
        dur=number(scene.get('duration_seconds'),f'Сцена {i}: duration_seconds',positive=True)
        elapsed+=dur;end_frame=round(elapsed*fps)
        if end_frame<=last_frame:raise RuntimeError(f'Сцена {i} не занимает ни одного кадра при {fps} fps')
        last_frame=end_frame
        for field in ('title','caption','narration'):
            if field in scene and not isinstance(scene[field],str):raise RuntimeError(f'Сцена {i}: {field} должен быть строкой')
        for field in ('asset_id','video_asset_id'):
            if field in scene and (not isinstance(scene[field],str) or not scene[field].strip()):raise RuntimeError(f'Сцена {i}: неверный {field}')
        if scene['kind']!='nature' and any(field in scene for field in ('asset_id','video_asset_id','image_crop','video_offset_seconds','video_end_seconds')):raise RuntimeError(f'Сцена {i}: медиа-настройки поддерживаются только в kind=nature')
        if any(field in scene for field in ('video_offset_seconds','video_end_seconds')) and not scene.get('video_asset_id'):raise RuntimeError(f'Сцена {i}: диапазон видео требует video_asset_id')
        if scene['kind']=='nature' and not (scene.get('asset_id') or scene.get('video_asset_id')):raise RuntimeError(f'Сцена {i}: для пейзажа нужен ресурс')
        for field in ('narration_lead_seconds','narration_pause_seconds','video_offset_seconds','video_end_seconds'):
            if field in scene:number(scene[field],f'Сцена {i}: {field}')
        if scene.get('narration','').strip() and scene.get('narration_lead_seconds',.4)>=dur-.2:raise RuntimeError(f'Сцена {i}: нет времени для речи после отступа')
        if 'points' in scene and (not isinstance(scene['points'],list) or len(scene['points'])>3 or any(not isinstance(t,str) for t in scene['points'])):raise RuntimeError(f'Сцена {i}: points должен содержать до трёх строк')
        if 'image_crop' in scene:
            crop=scene['image_crop']
            if not isinstance(crop,list) or len(crop)!=4:raise RuntimeError('image_crop: нужны четыре доли')
            left,top,right,bottom=[number(v,'image_crop') for v in crop]
            if not (0<=left<right<=1 and 0<=top<bottom<=1):raise RuntimeError('image_crop выходит за границы фотографии')
            if scene.get('video_asset_id'):raise RuntimeError('image_crop применяется только к фотографии')
    if abs(scenes[0]['duration_seconds']-1)>1e-6:raise RuntimeError('Общее интро длится ровно 1 секунду')
    if abs(elapsed-target)>1e-6:raise RuntimeError(f'Сумма сцен {elapsed:g} с не совпадает с target_duration_seconds={target:g} с')
    narrated=any(s.get('narration','').strip() for s in scenes)
    if data['type']=='lesson' and not narrated:raise RuntimeError('Для урока нужна озвучка')
    if voice=='approved' and narrated and (data.get('approved_voice') is not True or style['voice'].get('approved_for_publication') is not True):raise RuntimeError('Голос не одобрен в сценарии и настройках')
    return data


def scenario_warnings(data):
    """Reading-time diagnostics; short intros/outros and lesson pacing remain valid."""
    if data.get('type')!='meditation' or data.get('caption_mode','stage')!='stage':return []
    warnings=[]
    for i,scene in enumerate(data['scenes'],1):
        caption=scene.get('caption','').strip()
        if scene['kind'] in ('intro','outro') or not caption:continue
        minimum=max(5.,len(caption.split())/2+2)
        if scene['duration_seconds']<minimum:
            warnings.append(f'Сцена {i}: подсказка показана только {scene["duration_seconds"]:g} с; ориентир для чтения — не менее {minimum:g} с. Для медитации обычно нужны более длинные интервалы практики.')
    return warnings
