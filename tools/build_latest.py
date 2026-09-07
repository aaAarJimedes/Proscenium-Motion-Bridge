"""Build a deterministic Blender extension archive from this repository."""
from pathlib import Path
import tomllib,zipfile,hashlib,json
root=Path(__file__).resolve().parents[1]
candidates=[p for p in [root/'extension/ba_animation_workflow/blender_manifest.toml',root/'proscenium_motion_bridge/blender_manifest.toml'] if p.exists()]
if len(candidates)!=1:raise RuntimeError('Expected one maintained extension manifest')
manifest=candidates[0];folder=manifest.parent
meta=tomllib.loads(manifest.read_text(encoding='utf8'))
dist=root/'dist';dist.mkdir(exist_ok=True)
archive=dist/(meta['id']+'-'+meta['version']+'.zip');hashes={}
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for p in sorted(folder.rglob('*')):
        if not p.is_file() or '__pycache__' in p.parts:continue
        rel=p.relative_to(folder).as_posix();body=p.read_bytes()
        entry=zipfile.ZipInfo(rel,(2026,9,7,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED;entry.external_attr=0o100644<<16
        z.writestr(entry,body);hashes[rel]=hashlib.sha256(body).hexdigest()
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
result={'module':meta['id'],'version':meta['version'],'archive':archive.name,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'source_files':hashes}
(dist/'build-manifest.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k!='source_files'}))
