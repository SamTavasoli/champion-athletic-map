"""Compare saved and reproduced analysis in the installed analysis environment."""
from pathlib import Path
import argparse
import json
import sys
from reproduction_compare import compare_outputs, comparison_policy


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    config=json.loads(Path(args.config).read_text(encoding='utf-8'))
    output=Path(config['comparison_json']);output.parent.mkdir(parents=True,exist_ok=True)
    try:
        if config['declared_policy'] != comparison_policy():
            raise ValueError('Comparison rules differ from the policy declared before execution.')
        if any(config[key]!=config['declared_policy'][key] for key in ('rtol','atol')):
            raise ValueError('Numerical tolerances differ from the policy declared before execution.')
        rows=compare_outputs(config['original_folder'],config['reproduced_folder'],{'rtol':config['rtol'],'atol':config['atol']})
        result={'schema_version':'step36-result-comparison-1','status':'passed' if rows and all(row['status']=='passed' for row in rows) else 'failed',
            'comparison_rows':rows,'files_compared':len(rows),'python':sys.executable}
    except Exception as exc:
        result={'schema_version':'step36-result-comparison-1','status':'failed','comparison_rows':[],
                'files_compared':0,'error_type':type(exc).__name__,'error':str(exc),'python':sys.executable}
    output.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
