"""Run one protected, results-only notebook replay in an independent environment."""
from __future__ import annotations
import csv
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback
import uuid
from _cam36_inputs import inspect_inputs, stage_inputs, verify_protected_inputs
from _cam36_environment import analysis_requirements, prepare_environment, isolated_environment, redact


def sha(raw):return hashlib.sha256(raw).hexdigest()


def encoded(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf-8')


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(encoded(value))


def csv_bytes(rows):
    stream=io.StringIO(newline='');fields=list(dict.fromkeys(k for row in rows for k in row)) if rows else ['status']
    writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader()
    for row in rows:writer.writerow({k:json.dumps(v,ensure_ascii=False,sort_keys=True) if isinstance(v,(list,dict)) else v for k,v in row.items()})
    return stream.getvalue().encode('utf-8-sig')


def require(condition,message):
    if not condition:raise ValueError(message)


def safe_command(command,env,cwd,stdout,stderr,timeout):
    with Path(stdout).open('w',encoding='utf-8') as out,Path(stderr).open('w',encoding='utf-8') as err:
        return subprocess.run(command,cwd=cwd,env=env,stdout=out,stderr=err,text=True,timeout=timeout,check=False).returncode


def notebook_for_replay(run,project):
    intro='''# Saved-analysis reproduction\n\nWe execute this results-only notebook in a new kernel in a separately installed environment. We read copied evidence, recalculate Step 35 and keep the original experiment unchanged. This notebook does not repeat the full project notebook, training or model generation.\n'''
    setup='''from pathlib import Path
import hashlib
import importlib.metadata
import json
import os
import platform
import site
import sys

project = Path.cwd().resolve()
settings = json.loads((project / "replay_settings.json").read_text(encoding="utf-8"))
assert settings["mode"] == "results_reproduction"
run = Path(settings["run_folder"])
sys.path.insert(0, str(project / "analysis_code"))
for name, expected in settings["software_sha256"].items():
    assert hashlib.sha256((project / "analysis_code" / (name + ".py")).read_bytes()).hexdigest() == expected
kernel_info = {"pid": os.getpid(), "sys_executable": sys.executable, "sys_prefix": sys.prefix,
    "sys_base_prefix": sys.base_prefix, "python_version": platform.python_version(),
    "user_site_enabled": bool(site.ENABLE_USER_SITE),
    "packages": {dist.metadata["Name"].lower().replace("_", "-"): dist.version
                 for dist in importlib.metadata.distributions() if dist.metadata.get("Name")}}
(run / "kernel_info.json").write_text(json.dumps(kernel_info, sort_keys=True, indent=2) + "\\n", encoding="utf-8")
network_attempts = []
def offline_analysis_guard(event, args):
    if event == "socket.connect":
        network_attempts.append({"event": event, "address": str(args[-1])})
        raise RuntimeError("Network access is disabled during saved-analysis reproduction.")
sys.addaudithook(offline_analysis_guard)
print("Results-only configuration loaded in the separate kernel.")
'''
    verify='''for relative, expected in settings["stage_files"].items():
    assert hashlib.sha256((project / relative).read_bytes()).hexdigest() == expected, relative
print("Saved inputs match the recorded versions.")
'''
    execute='''from step35_analysis_runner import analyze
configuration = json.loads((project / "analysis_configuration.json").read_text(encoding="utf-8"))
result = analyze(project, configuration)
assert result["new_model_calls"] == result["new_predictions"] == result["new_reference_queries"] == 0
(run / "replay_result.json").write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\\n", encoding="utf-8")
print("Saved analysis recalculated.")
'''
    finish='''integrity = []
for relative, expected in settings["stage_files"].items():
    actual = hashlib.sha256((project / relative).read_bytes()).hexdigest()
    integrity.append({"path": relative, "sha256_before": expected, "sha256_after": actual, "unchanged": actual == expected})
assert all(item["unchanged"] for item in integrity)
(run / "staged_input_integrity.json").write_text(json.dumps(integrity, sort_keys=True, indent=2) + "\\n", encoding="utf-8")
(run / "network_attempts.json").write_text(json.dumps(network_attempts, sort_keys=True, indent=2) + "\\n", encoding="utf-8")
assert not network_attempts
print("Copied inputs are unchanged. No network requests were made by the analysis.")
'''
    cells=[{'cell_type':'markdown','id':'replay-purpose','metadata':{},'source':intro.splitlines(keepends=True)}]
    for i,code in enumerate((setup,verify,execute,finish),1):cells.append({'cell_type':'code','id':'replay-'+str(i),'execution_count':None,'metadata':{},'outputs':[],'source':code.splitlines(keepends=True)})
    return {'cells':cells,'metadata':{'kernelspec':{'name':'step36-analysis','display_name':'Step 36 isolated analysis','language':'python'},'language_info':{'name':'python'}},'nbformat':4,'nbformat_minor':5}


def documentation(root,run,summary,requirements,comparison):
    pins='\n'.join(name+'=='+version for name,version in sorted(requirements.items()))
    relative=run.relative_to(root).as_posix()
    text='''# Results reproduction\n\nWe check a dedicated saved-results notebook in a new Python environment and a fresh kernel. We preserve the original experiment and compare its saved outputs with a separately recalculated copy.\n\n'''
    text+='Current verification: **'+summary['status']+'**. Source analysis: `'+str(summary.get('source_analysis_id'))+'`.\n\n'
    text+='## Tested route\n\nFrom the repository root, using the project Python interpreter:\n\n```powershell\npython '+relative+'/reproduce.py --project-root .\n```\n\n'
    text+='This creates another versioned verification run. It does not resume or overwrite this run. The route installs its analysis dependencies into a new environment; package downloads may require an internet connection during setup. The analysis itself runs with network access disabled. No existing project package versions are changed.\n\n'
    text+='The top-level analysis requirements for this run are:\n\n```text\n'+pins+'\n```\n\n'
    text+='The resolved dependency versions, installation command, package report and freeze are recorded under `environment/`. For setup from the resolved lock, use a separate environment and `python -m pip install -r environment/pip_freeze.txt`; that exact resolved-lock reinstallation is a documented route, not a separate tested claim. Source artifacts must be present under the original recorded project-relative paths. Missing evidence stops the check instead of triggering downloads, retraining or replacement responses.\n\n'
    text+='## What is compared\n\nWe verify IDs, statuses, counts, denominators, group membership and decoded bootstrap draws exactly. Documented numerical metrics use relative tolerance '+str(comparison['rtol'])+' and absolute tolerance '+str(comparison['atol'])+'. Figure source values and rendered labels/populations are checked; metadata or renderer-only changes are recorded separately. The full declared rules are in `verification_config.json`. Protected source files are hashed before and after the run.\n\n'
    text+='## Scope\n\nThis verification concerns the dedicated results-only notebook and the selected Step 35 evidence. It does not establish that all 39 steps of the main project notebook execute cleanly from the beginning. The historical Step 12 catalog notebook is retained as build history, not claimed to have been reexecuted here. Data rebuilding, training repetition and live-backend generation remain separate, untested procedures in this run. Recorded team decisions and the single assisted response review are loaded unchanged; independent teammate agreement is not invented.\n\n'
    text+='The run preserves the input inventory, environment, source code, standalone notebook, executed notebook, execution logs, result comparisons and protection checks. The external runner writes the completion record after notebook execution and comparison. Unexpected errors leave the partial notebook and failure details available.\n\n'
    text+='The setup supports Python virtual environments and Jupyter notebook execution. Relevant primary documentation: [Python venv](https://docs.python.org/3/library/venv.html) and [NBClient execution](https://nbclient.readthedocs.io/en/latest/client.html).\n'
    (run/'reproducibility.md').write_text(text,encoding='utf-8')
    doc=root/'docs/reproducibility.md';doc.parent.mkdir(parents=True,exist_ok=True)
    start='<!-- step36-results-reproduction-start -->';end='<!-- step36-results-reproduction-end -->'
    block=start+'\n\n## Step 36 — Saved-results reproduction\n\nLatest verification: **'+summary['status']+'**. Tested route and scope: ['+relative+'/reproducibility.md](../'+relative+'/reproducibility.md).\n\n'+end
    existing=doc.read_text(encoding='utf-8') if doc.exists() else '# Project reproducibility\n'
    if doc.exists():(run/'previous_reproducibility_document.md').write_bytes(doc.read_bytes())
    if start in existing and end in existing and existing.index(start)<existing.index(end):
        a=existing.index(start);b=existing.index(end)+len(end);updated=existing[:a]+block+existing[b:]
    else:updated=existing.rstrip()+'\n\n'+block+'\n'
    doc.write_text(updated,encoding='utf-8')
    return 'docs/reproducibility.md'


def run_verification(root,bundle,emit=None,configuration=None):
    root=Path(root).resolve();emit=emit or (lambda message:None);configuration=dict(configuration or {})
    require(configuration.get('mode','results_reproduction')=='results_reproduction','This runner supports saved-results reproduction only.')
    run_id='repro_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    run=root/'results/reproducibility'/run_id;run.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();inventory=None;comparison={'comparison_rows':[],'status':'not_run'};environment={'status':'not_run'};kernel={'status':'not_run'};staging=None
    integrity=[];error=None;requirements={};mode='results_reproduction'
    def event(phase,status,**extra):
        row={'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'phase':phase,'status':status,**extra}
        with (run/'execution_log.jsonl').open('a',encoding='utf-8') as handle:handle.write(json.dumps(redact(row),sort_keys=True,allow_nan=False)+'\n')
    policy=bundle['comparison_policy']
    config={'schema_version':'step36-verification-config-1','run_id':run_id,'mode':mode,'project_root':str(root),'run_folder':str(run),
        'environment_mode':'fresh_install','kernel_transport':'ipc' if os.name=='posix' else 'tcp','comparison_policy':policy,
        'numeric_comparison':{'rtol':1e-10,'atol':1e-12},'cell_execution_timeout_seconds':1200,'kernel_startup_timeout_seconds':60,
        'notebook_scope':'dedicated_saved_results_notebook','full_main_notebook_execution_claimed':False,'data_rebuild':False,'training_repetition':False,'live_generation':False,
        'software_sha256':bundle['software_sha256'],'new_model_calls':0,'new_predictions':0}
    try:
        revision=subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,text=True,timeout=15,check=False)
        if revision.returncode==0:
            changed=subprocess.run(['git','-C',str(root),'status','--porcelain','--untracked-files=no'],capture_output=True,text=True,timeout=15,check=False)
            config['source_revision']={'commit':revision.stdout.strip(),'tracked_changes_present':bool(changed.stdout.strip()) if changed.returncode==0 else None}
        else:config['source_revision']={'commit':None,'reason':'Git revision unavailable; exact analysis/reproduction source hashes are recorded.'}
    except Exception:
        config['source_revision']={'commit':None,'reason':'Git command unavailable; exact source hashes are recorded.'}
    save(run/'verification_config.json',config)
    save(run/'reproduction_notebook.ipynb',notebook_for_replay(run,run/'project'))
    save(run/'executed_notebook.ipynb',notebook_for_replay(run,run/'project'))
    (run/'.gitignore').write_text('environment/venv/\nproject/\njupyter_data/\njupyter_runtime/\nipython/\nmatplotlib_config/\njupyter_config/\n',encoding='utf-8')
    software=run/'software';software.mkdir()
    for name,source in bundle['step36_sources'].items():
        require(sha(source.encode('utf-8'))==bundle['software_sha256'][name],'Reproduction helper differs from its saved source: '+name)
        (software/(name+'.py')).write_bytes(source.encode('utf-8'))
    save(run/'reproduction_package.json',bundle)
    replay_cli='''from pathlib import Path\nimport argparse,json,sys,types,hashlib\nbase=Path(__file__).resolve().parent\np=argparse.ArgumentParser();p.add_argument('--project-root',required=True);a=p.parse_args()\nraw=(base/'reproduction_package.json').read_bytes()\nif hashlib.sha256(raw).hexdigest()!='__BUNDLE_SHA__':raise ValueError('The saved reproduction package has changed.')\nb=json.loads(raw)\nfor name,key in [('_cam36_inputs','reproduction_inputs'),('_cam36_environment','reproduction_environment'),('_cam36_coordinator','reproduction_coordinator')]:\n m=types.ModuleType(name);m.__file__=str(base/'software'/(key+'.py'));sys.modules[name]=m;exec(compile(b['step36_sources'][key],m.__file__,'exec'),m.__dict__)\nr=sys.modules['_cam36_coordinator'].run_verification(Path(a.project_root),b,emit=print)\nprint('Step 36 — Reproducibility check:',r['status'])\nif r['status']!='passed':raise SystemExit(1)\n'''
    (run/'reproduce.py').write_bytes(replay_cli.replace('__BUNDLE_SHA__',sha(encoded(bundle))).encode('utf-8'))
    event('configuration','recorded')
    try:
        inventory=inspect_inputs(root,bundle['step35']['package']['software_sha256'])
        require(inventory['identity']['source_member_sha256']==bundle['step35']['package']['source_member_sha256'],'The selected analysis belongs to another saved experiment.')
        save(run/'input_manifest.json',inventory);save(run/'source_analysis_summary.json',inventory['summary'])
        config['source_analysis_id']=inventory['analysis_id'];save(run/'verification_config.json',config);event('inputs','verified',files=inventory['file_count'])
        emit('Preparing the separate analysis environment…')
        requirements=analysis_requirements(inventory['identity']['bootstrap_settings']['numpy_version'])
        environment=prepare_environment(run,requirements,{'environment_mode':'fresh_install',**configuration.get('environment',{})},emit=None)
        config['requirements']=requirements;save(run/'verification_config.json',config)
        require(environment['status']=='passed','The separate environment could not be prepared. Its setup logs were retained.')
        event('environment','installed')
        project=run/'project';staging=stage_inputs(root,project,inventory);save(run/'staged_input_report.json',staging)
        code=project/'analysis_code';code.mkdir()
        for name,source in bundle['step35']['modules'].items():
            require(sha(source.encode('utf-8'))==bundle['step35']['package']['software_sha256'][name],'An original Step 35 helper differs from its saved identity.')
            (code/(name+'.py')).write_bytes(source.encode('utf-8'))
        save(project/'analysis_configuration.json',bundle['step35']['package'])
        settings={'mode':mode,'run_folder':str(run),'software_sha256':bundle['step35']['package']['software_sha256'],'stage_files':staging['files']}
        save(project/'replay_settings.json',settings)
        save(run/'reproduction_notebook.ipynb',notebook_for_replay(run,project))
        save(run/'executed_notebook.ipynb',notebook_for_replay(run,project))
        driver={'run_folder':str(run),'stage_root':str(project),'notebook_path':str(run/'reproduction_notebook.ipynb'),'python':environment['python'],
            'kernel_name':environment['kernel_name'],'execution_timeout':1200,'startup_timeout':60,'kernel_transport':config['kernel_transport']}
        save(run/'driver_config.json',driver)
        emit('Replaying the saved analysis in a fresh kernel…')
        env=isolated_environment(run,environment['python'])
        rc=safe_command([environment['python'],str(software/'notebook_driver.py'),'--config',str(run/'driver_config.json')],env,run,
            run/'notebook_stdout.log',run/'notebook_stderr.log',5400)
        kernel=json.loads((run/'kernel_execution.json').read_bytes()) if (run/'kernel_execution.json').is_file() else {'status':'failed','error':'No external kernel completion record.'}
        require(rc==0 and kernel['status']=='passed','The separate notebook execution needs attention; the partial notebook and logs were retained.')
        event('kernel','completed',cells=kernel.get('code_cell_count'))
        recalculated=json.loads((run/'replay_result.json').read_bytes());reproduced=project/recalculated['analysis_folder']
        comp_config={'original_folder':str(root/inventory['analysis_folder']),'reproduced_folder':str(reproduced),
            'comparison_json':str(run/'comparison_results.json'),'declared_policy':policy,'rtol':1e-10,'atol':1e-12}
        save(run/'comparison_config.json',comp_config)
        rc=safe_command([environment['python'],str(software/'comparison_driver.py'),'--config',str(run/'comparison_config.json')],env,run,
            run/'comparison_stdout.log',run/'comparison_stderr.log',180)
        comparison=json.loads((run/'comparison_results.json').read_bytes()) if (run/'comparison_results.json').is_file() else {'status':'failed','comparison_rows':[],'error':'No comparison record.'}
        (run/'result_comparison.csv').write_bytes(csv_bytes(comparison['comparison_rows']))
        require(rc==0 and comparison['status']=='passed','Some reproduced results differ. Both versions and the comparison report were retained.')
        require((run/'network_attempts.json').is_file() and json.loads((run/'network_attempts.json').read_bytes())==[],'The saved analysis did not confirm offline execution.')
        stage_integrity=json.loads((run/'staged_input_integrity.json').read_bytes())
        require(stage_integrity and all(row['unchanged'] for row in stage_integrity),'Copied inputs changed during analysis.')
        event('comparison','matched',files=comparison.get('files_compared'))
    except Exception as exc:
        error={'error_type':type(exc).__name__,'message':redact(str(exc))}
        save(run/'failure_details.json',{**error,'traceback':redact(traceback.format_exc())});event('verification','failed',**error)
    finally:
        if (run/'kernel_execution.json').is_file():
            try:
                observed_kernel=json.loads((run/'kernel_execution.json').read_bytes())
                require(isinstance(observed_kernel,dict),'Kernel completion record must be a JSON object.')
                kernel=observed_kernel
                if kernel.get('status')=='running' and error is not None:
                    kernel={**kernel,'status':'interrupted_or_failed'}
            except Exception as record_error:
                kernel={'status':'failed','error':'Invalid retained kernel completion record: '+str(record_error)}
                error=error or {'error_type':'KernelRecordError','message':kernel['error']}
        if inventory is not None:
            try:integrity=verify_protected_inputs(root,inventory)
            except Exception as exc:
                integrity=[{'path':'protected_inventory','sha256_before':None,'sha256_after':None,'unchanged':False,'error':redact(str(exc))}]
            (run/'input_integrity_checks.csv').write_bytes(csv_bytes(integrity))
            if not integrity or not all(row['unchanged'] for row in integrity):
                error=error or {'error_type':'SourceIntegrityError','message':'A protected source input changed; the difference was retained.'}
        passed=(error is None and environment.get('status')=='passed' and kernel.get('status')=='passed' and comparison.get('status')=='passed'
                and bool(integrity) and all(row['unchanged'] for row in integrity))
        checks=[{'check':'independent_dependency_installation','status':environment.get('status','not_run')},
            {'check':'fresh_kernel_notebook_execution','status':kernel.get('status','not_run')},
            {'check':'saved_analysis_outputs','status':comparison.get('status','not_run')},
            {'check':'protected_originals','status':'passed' if integrity and all(row['unchanged'] for row in integrity) else 'not_verified'},
            {'check':'full_main_notebook_execution','status':'not_tested'}, {'check':'data_rebuild','status':'not_tested'},
            {'check':'training_repetition','status':'not_tested'}, {'check':'live_generation','status':'not_tested'}]
        (run/'verification_checks.csv').write_bytes(csv_bytes(checks))
        summary={'schema_version':'step36-reproducibility-1','status':'passed' if passed else 'needs_attention','run_id':run_id,
            'source_analysis_id':inventory['analysis_id'] if inventory else None,'source_analysis_status':inventory['summary']['status'] if inventory else None,
            'scope':'dedicated_saved_results_notebook','source_classifier_status':inventory['summary']['classifier']['status'] if inventory else None,
            'fresh_dependency_installation':environment.get('status','not_run'),'fresh_kernel_execution':kernel.get('status','not_run'),
            'result_comparison':comparison.get('status','not_run'),'files_compared':comparison.get('files_compared',0),
            'protected_files':len(integrity),'protected_inputs_unchanged':bool(integrity) and all(row['unchanged'] for row in integrity),
            'full_main_notebook_execution':'not_tested','data_rebuild':'not_tested','training_repetition':'not_tested','live_generation':'not_tested',
            'new_model_calls':0,'new_predictions':0,'new_reference_queries':0,'review_ratings_changed':False,
            'original_independent_teammate_agreement':'not_collected','elapsed_seconds':round(time.monotonic()-started,3),
            'verification_folder':run.relative_to(root).as_posix(),'executed_notebook':(run/'executed_notebook.ipynb').relative_to(root).as_posix(),
            'comparison_path':(run/'result_comparison.csv').relative_to(root).as_posix(),'error':error,
            'source_unavailable_components_preserved':'verified' if comparison.get('status')=='passed' else 'not_verified',
            'source_saved_component_statuses':{'classifier':inventory['identity']['classifier_status']['status'],'retrieval':inventory['identity']['retrieval_status'],'native_runtime':inventory['identity']['native_runtime_status']} if inventory else None}
        save(run/'verification_summary.json',summary)
        try:
            summary['documentation_path']=documentation(root,run,summary,requirements,policy)
        except Exception as doc_error:
            summary.update(status='needs_attention',documentation_status='update_failed',documentation_error=redact(str(doc_error)))
        report=['# Step 36 — Reproducibility check','',
            'Status: **'+summary['status']+'**. Scope: a dedicated results-only notebook in a new environment and kernel.','',
            '| Check | Result |','|---|---|']
        report.extend('| '+item['check'].replace('_',' ')+' | '+item['status']+' |' for item in checks)
        report.extend(['','Source analysis: `'+str(summary['source_analysis_id'])+'`. Compared files: '+str(summary['files_compared'])+'. Protected files: '+str(summary['protected_files'])+'.',
            '', 'The comparison uses the declared exact/tolerance rules. Source outputs and copied inputs are checked separately; absent measurements and review limitations stay in their original states.',
            '', 'This record does not claim a complete Run All of the main project notebook, new data preparation, retraining or live model generation.'])
        if error:report.extend(['','Issue: '+error['message']])
        (run/'verification_report.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
        summary['report_path']=(run/'verification_report.md').relative_to(root).as_posix()
        save(run/'verification_summary.json',summary)
        pointer=root/'results/step36_reproducibility_summary.json'
        if pointer.exists():require(json.loads(pointer.read_bytes()).get('schema_version')=='step36-reproducibility-1','An unrelated Step 36 summary was preserved.')
        save(pointer,summary)
        event('verification',summary['status'],protected_unchanged=summary['protected_inputs_unchanged'])
    return summary
