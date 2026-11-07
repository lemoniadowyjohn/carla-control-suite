#!/usr/bin/env python3
"""Structural guardrail only; does not independently attest execution, authority, logs or science."""
import sys, json, re
from pathlib import Path
SHA=re.compile(r'^[0-9a-f]{40}$')
VALID={'PASS','FAIL','NOT_EXECUTED','BLOCKED_ENV','BLOCKED_AUTH','BLOCKED_EXTERNAL','PARTIAL','INCOMPLETE','REQUIRES_CHANGES','NOT_APPLICABLE_PLATFORM','OFFLINE_CERTIFIED_WITH_BLOCKERS'}

def check(d):
    errors=[]
    if d.get('schema')!='carla_ia_v27_evidence/v1': errors.append('invalid schema')
    if not SHA.fullmatch(str(d.get('inspected_baseline_sha') or '')): errors.append('invalid baseline SHA')
    c=d.get('candidate_sha')
    if c is not None and not SHA.fullmatch(str(c)): errors.append('invalid candidate SHA')
    if not isinstance(d.get('commands'),list): errors.append('commands must be list')
    for i,x in enumerate(d.get('commands',[]) if isinstance(d.get('commands'),list) else []):
        if not isinstance(x,dict): errors.append(f'commands[{i}] not object');continue
        st=x.get('status','NOT_EXECUTED')
        if st not in VALID: errors.append(f'commands[{i}] invalid status')
        if st=='PASS':
            if x.get('exit_code')!=0: errors.append(f'commands[{i}]: PASS without zero exit code')
            if not isinstance(x.get('argv'),list) or not x['argv']: errors.append(f'commands[{i}]: PASS without argv')
            if not isinstance(x.get('cwd'),str) or not x['cwd']: errors.append(f'commands[{i}]: PASS without cwd')
            if not isinstance(x.get('source_sha'),str) or not SHA.fullmatch(x['source_sha']): errors.append(f'commands[{i}]: PASS without exact source_sha')
            if not x.get('stdout_sha256') or not x.get('stderr_sha256'): errors.append(f'commands[{i}]: PASS without raw stdout+stderr digest')
            if any(k not in x for k in ('start_utc','end_utc','executable_version')): errors.append(f'commands[{i}]: PASS without time/tool evidence')
            if x.get('type')=='pytest':
                required=('collected','passed','failed','skipped','xfailed','nodeids','junit_sha256')
                if any(k not in x for k in required): errors.append(f'commands[{i}]: pytest PASS without counts/nodeids/JUnit digest')
                if x.get('failed')!=0: errors.append(f'commands[{i}]: pytest PASS with failures')
    gates=d.get('gate_statuses')
    if not isinstance(gates,dict): errors.append('gate_statuses missing')
    else:
        for k,v in gates.items():
            if v not in VALID: errors.append(f'{k} invalid status {v}')
    ext=d.get('external_runtime')
    if not isinstance(ext,dict): errors.append('external_runtime missing')
    elif ext.get('status')=='PASS':
        if not ext.get('actual_rpc_response_receipt') or not ext.get('server_identity'):
            errors.append('runtime PASS without real RPC response/identity')
        if not d.get('operator_authorization',{}).get('status')=='VERIFIED':
            errors.append('runtime PASS without verified operator authorization')
    if d.get('conclusion')=='PRODUCTION_READY': errors.append('schema cannot assert production approval')
    if d.get('gate_statuses',{}).get('scientific_admission')=='PASS':
        errors.append('validator cannot independently attest scientific PASS; require separate adjudicator')
    return errors

def main():
    if len(sys.argv)!=2: print('Usage: python validate_receipt.py RECEIPT.json',file=sys.stderr);return 2
    d=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    failures=check(d)
    print(json.dumps({'structural_status':'FAIL' if failures else 'PASS','errors':failures,'NOTE':'PASS is schema-only; not evidence that commands actually ran'},indent=2))
    return 0 if not failures else 1
if __name__=='__main__': raise SystemExit(main())
