"""Local authenticated smoke test; credentials and access tokens are never printed."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import httpx
from sqlalchemy import select
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models.user import User


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True)
    parser.add_argument('--pdf')
    parser.add_argument('--mode', choices=['page','region'], default='page')
    args = parser.parse_args()
    # Only ever target loopback. The caller runs this from backend/ with its local DB.
    with SessionLocal() as db:
        user = next((u for u in db.scalars(select(User).where(User.is_active.is_(True)))
                     if u.role and u.role.is_active and any(p.code == 'dashboard.view' for p in u.role.permissions)), None)
        if not user:
            raise RuntimeError('No authorized local account available')
        token = create_access_token(user.username)
    with httpx.Client(base_url='http://127.0.0.1:8000/api/v1/tools/ocr', headers={'Authorization': 'Bearer ' + token}, timeout=30) as client:
        response = client.get('/status')
        response.raise_for_status()
        print('worker_status:', json.dumps(response.json()['data']))
        cases = [('document', args.image, {}), ('kie', args.image, {'fields': 'merchant,total,date'}),
                 ('vqa', args.image, {'question': 'What is the total amount on this receipt?'})]
        if args.mode == 'region':
            cases = [('document', args.image, {'mode':'region'})]
        if args.pdf:
            cases.append(('document', args.pdf, {'mode':args.mode}))
        for task, path, fields in cases:
            started = time.monotonic()
            response = client.post('/jobs', data={'task': task, **fields}, files={'file': (Path(path).name, Path(path).read_bytes())})
            response.raise_for_status()
            job_id = response.json()['data']['id']
            deadline = time.monotonic() + 420
            while time.monotonic() < deadline:
                response = client.get('/jobs/' + job_id)
                response.raise_for_status()
                job = response.json()['data']
                if job['status'] in {'succeeded', 'failed', 'expired'}:
                    break
                time.sleep(2)
            else:
                raise RuntimeError('Job timed out: ' + job_id)
            print(json.dumps({'task': task, 'file': Path(path).name, 'status': job['status'],
                              'seconds': round(time.monotonic()-started, 2), 'pages': job['pages_total'],
                              'mode':job['mode'], 'regions':job['regions_total'],
                              'result_excerpt': job['result'][:500], 'error': job['error']}, ensure_ascii=False), flush=True)
            if job['status'] != 'succeeded':
                raise RuntimeError('OCR smoke case failed')


if __name__ == '__main__':
    main()
