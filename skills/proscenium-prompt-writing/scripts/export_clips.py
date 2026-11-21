#!/usr/bin/env python3
"""Validate a one-action-per-clip manifest and export clean paste text.

The manifest is a delivery helper, not a Proscenium interchange format.
Semantic atomicity and contact accuracy still require human review.
"""
import argparse
import json
import math
import re
from pathlib import Path


def validate(data):
    fps=data.get('fps')
    if isinstance(fps,bool) or not isinstance(fps,(int,float)) or not math.isfinite(fps) or fps<=0:
        raise ValueError('fps must be a positive finite number')
    maximum=data.get('max_seconds')
    if maximum is not None and (isinstance(maximum,bool) or not isinstance(maximum,(int,float)) or not math.isfinite(maximum) or maximum<=0):
        raise ValueError('max_seconds must be a positive finite number')
    clips=data.get('clips')
    if not isinstance(clips,list) or not clips:
        raise ValueError('clips must be a nonempty list')
    seen=set()
    for c in clips:
        ident=c.get('id','')
        if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',ident) or ident in seen:
            raise ValueError('Each clip needs a unique safe id')
        seen.add(ident)
        p=c.get('prompt')
        if not isinstance(p,str) or not p.strip() or len(p)>1000 or '\n' in p or '\r' in p:
            raise ValueError(f'{ident}: prompt must be one nonempty line of at most 1000 characters')
        if any(k in c for k in ('prompt_blocks','pose_prompts','clips')):
            raise ValueError(f'{ident}: nested generation units are not a single clip')
        n=c.get('frames')
        if isinstance(n,bool) or not isinstance(n,int) or n<2:
            raise ValueError(f'{ident}: frames must be an integer >= 2')
        if maximum is not None and n/fps>maximum+1e-9:
            raise ValueError(f'{ident}: exceeds configured duration limit')
        prev=0
        for a in c.get('anchors',[]):
            f=a.get('frame')
            if isinstance(f,bool) or not isinstance(f,int) or not 1<=f<=n or f<=prev:
                raise ValueError(f'{ident}: manual anchors must be ordered inside local 1-{n}')
            if not isinstance(a.get('pose'),str) or not a['pose'].strip():
                raise ValueError(f'{ident}: manual anchor description missing')
            prev=f
    return clips


def export(data,dest):
    clips=validate(data)  # validate entire pack before any write
    dest=Path(dest)
    outputs={}
    guide=[f"# 单动作生成卡\n\n{data['fps']:g} FPS；每段各生成一次。只复制英文框，手动关键帧与注释不进入提示框。\n"]
    start=1
    for c in clips:
        p,n=c['prompt'],c['frames'];end=start+n-1
        outputs[f"{c['id']}.txt"]=p+'\n'
        guide.append(f"## {c['id']} · {c.get('title',c['id'])}\n\n本地 1–{n}；全片 {start}–{end}；{n/data['fps']:.3f}s；{len(p)}/1000 字符。\n\n```text\n{p}\n```\n")
        if c.get('anchors'):
            guide.append('手动关键帧：\n\n| 本地帧 | 姿势 / 接触 |\n| --- | --- |')
            guide.extend(f"| {a['frame']} | {a['pose']} |" for a in c['anchors'])
        if c.get('notes'):guide.append('\n注：'+c['notes']+'\n')
        start=end+1
    guide.append(f'总计 {start-1} 帧，{(start-1)/data["fps"]:.3f} 秒。\n')
    outputs['生成指南.md']='\n'.join(guide)
    dest.mkdir(parents=True,exist_ok=True)
    conflicts=[name for name in outputs if (dest/name).exists()]
    if conflicts: raise FileExistsError('Output already exists: '+', '.join(conflicts))
    for name,body in outputs.items():(dest/name).write_text(body,encoding='utf8')
    return {'clips':len(clips),'frames':start-1,'seconds':(start-1)/data['fps'],'max_characters':max(len(c['prompt']) for c in clips)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args()
    try:print(json.dumps(export(json.loads(args.manifest.read_text(encoding='utf-8-sig')),args.output)))
    except (ValueError,OSError,TypeError,KeyError) as exc:parser.exit(1,str(exc)+'\n')
