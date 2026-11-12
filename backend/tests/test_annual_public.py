import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.services.annual_match import read_state, mutate, ROLES
from app.api.routers.annual_match import router, public_router

class PublicEventTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'event.db'
        self.patch = patch('app.services.annual_match.DB_PATH', self.path)
        self.patch.start()
        app = FastAPI()
        app.include_router(router, prefix='/api/v1')
        app.include_router(public_router, prefix='/api/v1')
        self.client = TestClient(app)
    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()
    def generate(self):
        s = read_state('real')
        for i, p in enumerate(s['players']):
            p['roles'] = [ROLES[i % 5]]
        s = mutate('real', s['revision'], 'save', {'players': s['players']})
        return mutate('real', s['revision'], 'tournament-generate')
    def publish(self, state, names=False, enabled=True):
        return mutate('real', state['revision'], 'tournament-public', {'enabled': enabled, 'show_names': names})
    def get(self, state):
        return self.client.get('/api/v1/public/annual-events/' + state['public_view']['token'])
    def test_anonymous_projection_and_names_opt_in(self):
        s = self.publish(self.generate())
        response = self.get(s)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        body = response.json()['data']
        self.assertEqual(set(body), {'updated_at', 'show_names', 'draw_enabled', 'revision', 'tournament'})
        t = body['tournament']
        self.assertEqual(len(t['matches']), 17)
        self.assertTrue(all(team['players'] == [] for team in t['teams']))
        for private in ('seed', 'snapshot', 'created_by', 'score_history', 'players', 'public_view', 'audit'):
            self.assertNotIn(private, body)
            if private != 'players': self.assertNotIn(private, t)
        self.assertTrue(all('updated_by' not in m and 'score_history' not in m for m in t['matches']))
        s = self.publish(s, names=True)
        players = [p for team in self.get(s).json()['data']['tournament']['teams'] for p in team['players']]
        self.assertEqual(len(players), 90)
        self.assertEqual(set(players[0]), {'id', 'name', 'role'})
    def test_disable_and_invalid_tokens(self):
        s = self.publish(self.generate())
        token = s['public_view']['token']
        s = self.publish(s, enabled=False)
        self.assertEqual(s['public_view']['token'], token)
        self.assertEqual(self.get(s).status_code, 404)
        for token in ('invalid', 'f'*32):
            self.assertEqual(self.client.get('/api/v1/public/annual-events/' + token).status_code, 404)
    def test_publication_guards_and_admin_auth(self):
        with self.assertRaises(ValueError): self.publish(read_state('real'))
        with self.assertRaises(ValueError): mutate('demo', 0, 'tournament-public', {'enabled': True})
        self.assertEqual(self.client.post('/api/v1/annual-match/real/tournament-public', json={'revision': 0, 'enabled': True}).status_code, 401)
        self.assertEqual(self.client.get('/api/v1/annual-match/real').status_code, 401)
    def test_host_draw_before_generation_and_five_snapshots(self):
        from types import SimpleNamespace
        from app.api.deps import get_current_user
        s = read_state('real')
        s = mutate('real', s['revision'], 'tournament-public', {'enabled': True, 'draw_enabled': True})
        token = s['public_view']['token']
        self.assertFalse(self.get(s).json()['data']['tournament']['generated'])
        url = '/api/v1/public/annual-events/' + token + '/draw'
        self.assertEqual(self.client.post(url, json={'revision': s['revision']}).status_code, 401)
        self.client.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=3, role=SimpleNamespace(is_active=True, permissions=[]))
        self.assertEqual(self.client.post(url, json={'revision': s['revision']}).status_code, 403)
        self.client.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=3, role=SimpleNamespace(is_active=True, permissions=[SimpleNamespace(code='system.users.manage')]))
        ids = []
        for i in range(9):
            rev = s['revision']
            response = self.client.post(url, json={'revision': rev})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn('team_draw_history', response.json()['data'])
            s = read_state('real')
            ids.append(s['tournament']['id'])
            self.assertEqual(sum(len(t['players']) for t in s['tournament']['teams']), (i + 1) * 10)
            self.assertNotIn('draw_plan', response.json()['data']['tournament'])
            self.assertEqual(response.json()['data']['tournament']['drawn_matches'], i + 1)
            self.assertEqual(self.client.post(url, json={'revision': rev}).status_code, 409)
        self.assertEqual([r['id'] for r in s['team_draw_history']], [ids[0]])
        self.assertEqual(len({p['id'] for t in s['tournament']['teams'] for p in t['players']}), 90)
        s = mutate('real', s['revision'], 'tournament-restore', {'id': ids[-2]})
        self.assertEqual(s['tournament']['id'], ids[-2])
        s = mutate('real', s['revision'], 'tournament-score', {'id': 'A1', 'score_a': 1, 'score_b': 0})
        record = next(r for r in s['team_draw_history'] if r['id'] == s['tournament']['id'])
        self.assertEqual(record['tournament']['matches'][0]['score_a'], 1)
        self.assertEqual(self.client.post(url, json={'revision': s['revision']}).status_code, 409)
        with self.assertRaises(ValueError): mutate('real', s['revision'], 'tournament-restore', {'id': ids[-1]})

    def test_draw_switch_and_token_enforced(self):
        s = self.publish(self.generate())
        with self.assertRaises(ValueError):
            mutate('real', s['revision'], 'tournament-public-draw', {'token': s['public_view']['token']})
        s = mutate('real', s['revision'], 'tournament-public', {'enabled': True, 'draw_enabled': True})
        with self.assertRaises(ValueError):
            mutate('real', s['revision'], 'tournament-public-draw', {'token': 'wrong'})
        s = mutate('real', s['revision'], 'tournament-public', {'enabled': False, 'draw_enabled': True})
        with self.assertRaises(ValueError):
            mutate('real', s['revision'], 'tournament-public-draw', {'token': s['public_view']['token']})

    def test_abandon_preserves_scores_and_can_restore(self):
        s = self.generate()
        identity = s['tournament']['id']
        s = mutate('real', s['revision'], 'tournament-score', {'id': 'A1', 'score_a': 2, 'score_b': 1})
        before_players = s['players']
        with self.assertRaises(ValueError): mutate('real', s['revision'], 'tournament-abandon', {'reason': ''})
        s = mutate('real', s['revision'], 'tournament-abandon', {'reason': '测试重抽'})
        self.assertFalse(s['tournament']['generated'])
        self.assertEqual(s['players'], before_players)
        record = next(r for r in s['team_draw_history'] if r['id'] == identity)
        self.assertEqual(record['status'], 'abandoned')
        self.assertEqual(record['tournament']['matches'][0]['score_a'], 2)
        self.assertEqual(len(s['team_draw_history']), 1)
        s = mutate('real', s['revision'], 'tournament-restore', {'id': identity})
        self.assertEqual(s['tournament']['matches'][0]['score_a'], 2)

    def test_team_rename_persists_and_is_public(self):
        s = self.publish(self.generate())
        s = mutate('real', s['revision'], 'tournament-rename', {'team_id': 'T01', 'name': 'alpha'})
        self.assertEqual(read_state('real')['tournament']['teams'][0]['name'], 'Alpha')
        self.assertEqual(self.get(s).json()['data']['tournament']['teams'][0]['name'], 'Alpha')
        with self.assertRaises(ValueError):
            mutate('real', s['revision'], 'tournament-rename', {'team_id': 'T02', 'name': 'Alpha'})

    def test_manual_qualifier_opponent_only(self):
        s = self.generate()
        with self.assertRaises(ValueError): mutate('real', s['revision'], 'tournament-challenge', {'team_id': 'T01'})
        for key in [f'A{i}' for i in range(1,10)] + [f'B{i}' for i in range(1,5)]:
            s = mutate('real', s['revision'], 'tournament-score', {'id': key, 'score_a': 2, 'score_b': 0})
        self.assertNotIn('challenge_slot', s['tournament'])
        opponent = next(m for m in s['tournament']['matches'] if m['id'] == 'B3')['winner']
        with self.assertRaises(ValueError): mutate('real', s['revision'], 'tournament-challenge', {'team_id': 'invalid'})
        s = mutate('real', s['revision'], 'tournament-challenge', {'team_id': opponent})
        self.assertEqual(s['tournament']['challenge_slot'], 'B3')
        self.assertEqual(s['tournament']['challenge_selection'], 'manual')
        with self.assertRaises(ValueError): mutate('real', s['revision'], 'tournament-challenge', {'team_id': opponent})

    def test_simulation_never_published(self):
        from app.services.annual_match import public_state
        s = self.publish(self.generate())
        for flag in ('simulated_roster', 'simulated_results'):
            s['tournament'][flag] = True
            with patch('app.services.annual_match.read_state', return_value=s):
                with self.assertRaises(ValueError): public_state(s['public_view']['token'])
            s['tournament'][flag] = False

    def test_public_score_refresh(self):
        s = self.publish(self.generate())
        s = mutate('real', s['revision'], 'tournament-score', {'id': 'A1', 'score_a': 2, 'score_b': 1})
        m = self.get(s).json()['data']['tournament']['matches'][0]
        self.assertEqual((m['score_a'], m['score_b']), (2, 1))
        self.assertIsNotNone(m['winner'])



    def test_readable_alias_preserves_visibility_and_old_link(self):
        s = self.publish(self.generate())
        alias = self.client.get('/api/v1/public/annual-events/annual-games')
        self.assertEqual(alias.status_code, 200)
        self.assertEqual(alias.json(), self.get(s).json())
        self.assertEqual(self.client.get('/api/v1/public/annual-events/unknown-event').status_code, 404)
        self.assertIn(self.client.post('/api/v1/public/annual-events/annual-games/draw',json={'revision':s['revision']}).status_code,[401,403])
        self.publish(s, enabled=False)
        self.assertEqual(self.client.get('/api/v1/public/annual-events/annual-games').status_code,404)

if __name__ == '__main__': unittest.main()
