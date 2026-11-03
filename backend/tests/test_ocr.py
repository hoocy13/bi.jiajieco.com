import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.api.routers.ocr import router
from app.core.config import settings
from app.db.session import Base, get_db
from app.models.ocr import OcrJob, OcrWorker


class OcrQueueTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine, tables=[OcrJob.__table__, OcrWorker.__table__])
        self.user = SimpleNamespace(id=11, role=SimpleNamespace(is_active=True, permissions=[SimpleNamespace(code='dashboard.view')]))
        app = FastAPI()
        app.include_router(router, prefix='/api/v1')
        app.dependency_overrides[get_current_user] = lambda: self.user

        def database():
            with Session(self.engine) as db:
                yield db

        app.dependency_overrides[get_db] = database
        self.key = 'test-worker-key-' + 'x' * 32
        self.patch = patch.object(settings, 'OCR_WORKER_KEY', self.key)
        self.patch.start()
        self.client = TestClient(app)
        self.base = '/api/v1/tools/ocr'
        self.headers = {'X-OCR-Worker-Key': self.key}

    def tearDown(self):
        self.client.close()
        self.patch.stop()
        self.engine.dispose()

    def submit(self, **form):
        response = self.client.post(self.base + '/jobs', data=form, files={'file': ('receipt.png', b'\x89PNG\r\n\x1a\nfixture', 'image/png')})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['data']

    def claim(self):
        return self.client.post(self.base + '/worker/poll', json={'ready': True}, headers=self.headers).json()['data']

    def test_claim_once_owner_isolation_and_completion(self):
        job = self.submit(task='kie', fields='date,total', max_tokens=1234)
        claimed = self.claim()
        self.assertEqual(claimed['id'], job['id'])
        self.assertEqual(claimed['max_tokens'], 1234)
        self.assertIsNone(self.claim())
        self.user.id = 22
        self.assertEqual(self.client.get(self.base + '/jobs/' + job['id']).status_code, 404)
        self.assertEqual(self.client.get(self.base + '/jobs/' + job['id'] + '/file').status_code, 404)
        self.assertEqual(self.client.get(self.base + '/jobs').json()['data'], [])
        self.user.id = 11
        self.assertEqual(self.client.get(self.base + '/jobs/' + job['id'] + '/file').content, b'\x89PNG\r\n\x1a\nfixture')
        headers = {**self.headers, 'X-OCR-Lease': claimed['lease']}
        path = self.base + '/worker/jobs/' + job['id']
        self.assertEqual(self.client.get(path + '/file', headers=headers).content, b'\x89PNG\r\n\x1a\nfixture')
        self.assertEqual(self.client.post(path + '/finish', json={'result': '{"total":"5.90"}'}, headers=headers).status_code, 200)
        self.assertEqual(self.client.post(path + '/finish', json={'result': 'overwrite'}, headers=headers).status_code, 409)
        self.assertEqual(self.client.get(self.base + '/jobs/' + job['id']).json()['data']['status'], 'succeeded')

    def test_expired_lease_reclaimed_and_old_worker_rejected(self):
        job = self.submit()
        old = self.claim()
        with Session(self.engine) as db:
            db.get(OcrJob, job['id']).lease_until = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
        new = self.claim()
        self.assertNotEqual(old['lease'], new['lease'])
        path = self.base + '/worker/jobs/' + job['id'] + '/heartbeat'
        self.assertEqual(self.client.post(path, json={}, headers={**self.headers, 'X-OCR-Lease': old['lease']}).status_code, 409)
        self.assertEqual(self.client.post(path, json={}, headers={**self.headers, 'X-OCR-Lease': new['lease']}).status_code, 200)

    def test_retention_clears_file_and_result_and_blocks_worker(self):
        job = self.submit()
        claimed = self.claim()
        with Session(self.engine) as db:
            row = db.get(OcrJob, job['id'])
            row.expires_at = datetime.utcnow() - timedelta(seconds=1)
            row.result = 'private result'
            db.commit()
        self.client.get(self.base + '/jobs')
        self.assertEqual(self.client.get(self.base + '/jobs/' + job['id'] + '/file').status_code, 410)
        with Session(self.engine) as db:
            row = db.get(OcrJob, job['id'])
            self.assertEqual((row.status, row.source, row.result), ('expired', b'', ''))
        self.assertEqual(self.client.get(self.base + '/worker/jobs/' + job['id'] + '/file', headers={**self.headers, 'X-OCR-Lease': claimed['lease']}).status_code, 409)

    def test_validation_capacity_and_worker_auth(self):
        self.assertEqual(self.client.post(self.base + '/worker/poll', json={'ready': True}).status_code, 401)
        self.assertIsNone(self.client.post(self.base + '/worker/poll', json={'ready': False}, headers=self.headers).json()['data'])
        self.assertFalse(self.client.get(self.base + '/status').json()['data']['online'])
        self.assertEqual(self.client.post(self.base + '/jobs', data={'task':'vqa'}, files={'file':('a.jpg',b'\xff\xd8\xffx')}).status_code, 422)
        self.assertEqual(self.client.post(self.base + '/jobs', files={'file':('a.png',b'not an image')}).status_code, 415)
        self.assertEqual(self.client.post(self.base + '/jobs', data={'max_tokens':16385}, files={'file':('a.png',b'\x89PNG\r\n\x1a\nx')}).status_code, 422)
        self.assertEqual(self.client.post(self.base + '/jobs', data={'task':'kie'}, files={'file':('a.pdf',b'%PDF-1.7')}).status_code, 422)
        for _ in range(3): self.submit()
        self.assertEqual(self.client.post(self.base + '/jobs', files={'file':('a.png',b'\x89PNG\r\n\x1a\nx')}).status_code, 429)

    def test_delete_cancels_running_job_and_permissions_enforced(self):
        job = self.submit()
        claimed = self.claim()
        self.assertEqual(self.client.delete(self.base + '/jobs/' + job['id']).status_code, 200)
        self.assertEqual(self.client.post(self.base + '/worker/jobs/' + job['id'] + '/finish', json={'result':'late result'}, headers={**self.headers,'X-OCR-Lease':claimed['lease']}).status_code, 409)
        self.user.role.permissions = []
        self.assertEqual(self.client.get(self.base + '/jobs').status_code, 403)

    def test_export_requires_login_and_returns_attachment(self):
        response = self.client.post(self.base + '/export', data={'content':'sample', 'token':'invalid-test-value'})
        self.assertEqual(response.status_code, 401)
        with patch('app.api.routers.ocr.get_current_user', return_value=self.user):
            response = self.client.post(self.base + '/export', data={'content':'{"total":"5.90"}', 'format':'json', 'token':'test-fixture'})
            self.assertEqual(response.status_code, 200)
            self.assertIn('attachment;', response.headers['content-disposition'])
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(response.json(), {'total':'5.90'})
            self.user.role.permissions = []
            self.assertEqual(self.client.post(self.base + '/export', data={'content':'sample', 'token':'test-fixture'}).status_code, 403)

    def test_region_capability_gates_claim_and_progress(self):
        region = self.submit(mode='region')
        page = self.submit()
        self.assertEqual(self.claim()['id'], page['id'])
        self.assertIsNone(self.claim())
        response = self.client.post(self.base + '/worker/poll', json={'ready':True,'region_ready':True}, headers=self.headers)
        claim = response.json()['data']
        self.assertEqual((claim['id'],claim['mode']), (region['id'],'region'))
        self.assertTrue(self.client.get(self.base + '/status').json()['data']['region_ready'])
        response = self.client.post(self.base + '/worker/jobs/' + region['id'] + '/heartbeat',
            json={'pages_total':1,'regions_done':2,'regions_total':5}, headers={**self.headers,'X-OCR-Lease':claim['lease']})
        self.assertEqual(response.status_code,200)
        data = self.client.get(self.base + '/jobs/' + region['id']).json()['data']
        self.assertEqual((data['regions_done'],data['regions_total']),(2,5))
        response = self.client.post(self.base + '/jobs', data={'task':'kie','mode':'region'}, files={'file':('a.png',b'\x89PNG\r\n\x1a\nfixture')})
        self.assertEqual(response.status_code,422)


if __name__ == '__main__':
    unittest.main()
