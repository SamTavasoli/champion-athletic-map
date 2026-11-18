from pathlib import Path
import argparse,json,sys,types,hashlib
base=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--project-root',required=True);a=p.parse_args()
raw=(base/'reproduction_package.json').read_bytes()
if hashlib.sha256(raw).hexdigest()!='a70c03cfd8d8e7ef00552cce30d25ad745409953ca36ceba34304825b3816ad3':raise ValueError('The saved reproduction package has changed.')
b=json.loads(raw)
for name,key in [('_cam36_inputs','reproduction_inputs'),('_cam36_environment','reproduction_environment'),('_cam36_coordinator','reproduction_coordinator')]:
 m=types.ModuleType(name);m.__file__=str(base/'software'/(key+'.py'));sys.modules[name]=m;exec(compile(b['step36_sources'][key],m.__file__,'exec'),m.__dict__)
r=sys.modules['_cam36_coordinator'].run_verification(Path(a.project_root),b,emit=print)
print('Step 36 — Reproducibility check:',r['status'])
if r['status']!='passed':raise SystemExit(1)
