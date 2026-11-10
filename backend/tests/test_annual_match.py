import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.deps import get_current_user
from app.api.routers.annual_match import router

from app.services.annual_match import NAMES, ROLES, eligible, initial_state, match, match_round, mutate, read_state


class AnnualMatchTests(unittest.TestCase):
    def test_bulk_global_matching_and_shortage(self):
        players = initial_state('demo')['players'][:20]
        for i, p in enumerate(players):
            p['roles'] = [ROLES[0 if i < 3 else 1 if i < 7 else 2 if i < 11 else 3 if i < 15 else 4]]
        players[-1]['roles'] = ['游走', '对抗路']
        games = match_round(players, 'global')
        self.assertEqual(len(games), 2)
        self.assertEqual(games, match_round(players, 'global'))
        self.assertEqual(len({p['id'] for game in games for p in game}), 20)
        for game in games:
            for team in ('red', 'blue'):
                self.assertEqual({p['role'] for p in game if p['team'] == team}, set(ROLES))
            for p in game:
                self.assertIn(p['role'], next(item for item in players if item['id'] == p['id'])['roles'])
        players[-1]['roles'] = ['游走']
        self.assertEqual(len(match_round(players, 'shortage')), 1)

    def test_bulk_preserves_draft_and_locks_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bulk.db'
            state = mutate('demo', 0, 'draw', path=path)
            draft = state['draft']
            state = mutate('demo', state['revision'], 'draw-all', path=path)
            batch = state['batch']
            self.assertIsNone(state['draft'])
            self.assertEqual(batch['matches'][0]['id'], draft['id'])
            self.assertEqual(batch['matches'][0]['slots'], draft['slots'])
            self.assertEqual(len(batch['matches']), 9)
            self.assertEqual(len({p['id'] for m in batch['matches'] for p in m['slots']}), 90)
            for action in ('draw', 'draw-all', 'save', 'next-round'):
                with self.assertRaises(ValueError):
                    mutate('demo', state['revision'], action, path=path)
            state = mutate('demo', state['revision'], 'lock-all', {'id': batch['id']}, path, actor=7)
            self.assertEqual(len(state['history']), 9)
            self.assertEqual(len(eligible(state)), 1)
            self.assertTrue(all(m['completed_by'] == 7 for m in state['history']))
            with self.assertRaises(ValueError):
                mutate('demo', state['revision'] - 1, 'lock-all', {'id': batch['id']}, path)
            self.assertEqual(len(read_state('demo', path)['history']), 9)

    def test_bulk_default_unknown_and_discard(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'discard.db'
            real = mutate('real', 0, 'draw-all', path=path)
            self.assertEqual(len(real['batch']['matches']), 9)
            state = mutate('demo', 0, 'draw-all', path=path)
            self.assertEqual(len(read_state('demo', path)['batch']['matches']), 9)
            batch_id = state['batch']['id']
            with self.assertRaises(ValueError):
                mutate('demo', state['revision'], 'discard-all', {'id': batch_id}, path)
            state = mutate('demo', state['revision'], 'discard-all', {'id': batch_id, 'reason': '演练'}, path)
            self.assertEqual(len(eligible(state)), 91)
            self.assertTrue(all(m['status'] == 'discarded' for m in state['history']))

    def test_http_permissions_validation_and_revision(self):
        app = FastAPI()
        app.include_router(router, prefix='/api/v1')
        with tempfile.TemporaryDirectory() as directory, patch('app.services.annual_match.DB_PATH', Path(directory) / 'api.db'):
            client = TestClient(app)
            self.assertEqual(client.get('/api/v1/annual-match/demo').status_code, 401)
            app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role=SimpleNamespace(is_active=True, permissions=[]))
            self.assertEqual(client.get('/api/v1/annual-match/demo').status_code, 403)
            app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role=SimpleNamespace(is_active=True, permissions=[SimpleNamespace(code='system.users.manage')]))
            self.assertEqual(client.get('/api/v1/annual-match/unknown').status_code, 422)
            self.assertEqual(client.get('/api/v1/annual-match/real').json()['data']['players'][0]['roles'], [])
            result = client.post('/api/v1/annual-match/demo/draw', json={'revision': 0})
            self.assertEqual(result.status_code, 200)
            draft = result.json()['data']['draft']
            self.assertEqual(draft['created_by'], 1)
            self.assertEqual(client.post('/api/v1/annual-match/demo/draw', json={'revision': 0}).status_code, 409)
            self.assertEqual(client.post('/api/v1/annual-match/demo/save', json={'revision': 1}).status_code, 422)
            result = client.post('/api/v1/annual-match/demo/lock', json={'revision': 1, 'id': draft['id']})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['data']['history'][0]['completed_by'], 1)

    def test_combined_preferences_attendance_and_fill(self):
        players = initial_state('demo')['players'][:12]
        players[0]['present'] = False
        players[10]['roles'] = ['对抗路', '打野']
        players[11]['roles'] = ['游走']
        slots = match(eligible(dict(players=players, history=[], round=1)), 'filters')
        self.assertNotIn('1', {p['id'] for p in slots})
        for p in slots:
            source = next(item for item in players if item['id'] == p['id'])
            self.assertIn(p['role'], source['roles'])
        players = initial_state('demo')['players'][:10]
        players[0]['roles'] = ['打野']
        with self.assertRaises(ValueError):
            match(players, 'no-fill')
        players[0]['fill'] = True
        slots = match(players, 'fill')
        self.assertEqual(sum(p['rank'] == 10 for p in slots), 1)

    def test_round_waiting_priority(self):
        players = initial_state('demo')['players'][:15]
        for p in players[:10]:
            p['round_penalty'] = 100
        slots = match(players, 'waiting')
        self.assertTrue({p['id'] for p in players[10:]}.issubset({p['id'] for p in slots}))

    def test_blank_roles_fill_gaps_without_overriding_fixed_preferences(self):
        players = [dict(id=str(i), name=str(i), roles=[ROLES[i]] if i < 5 else [], fill=False) for i in range(10)]
        for slots in (match(players, 'mixed'), match_round(players, 'mixed')[0]):
            self.assertEqual(len({p['id'] for p in slots}), 10)
            for p in slots:
                if int(p['id']) < 5:
                    self.assertEqual(p['role'], ROLES[int(p['id'])])
                else:
                    self.assertEqual(p['rank'], 11)

    def test_roster_and_unknown_roles(self):
        self.assertEqual(len(NAMES), 91)
        self.assertEqual(len(set(NAMES)), 91)
        slots = match(initial_state('real')['players'], 'a')
        self.assertEqual(len(slots), 10)
        self.assertTrue(all(p['rank'] == 11 for p in slots))
        self.assertEqual(len(match_round(initial_state('real')['players'], 'blank')), 9)

    def test_preferences_and_non_greedy_matching(self):
        players = [dict(id=str(i), name=str(i), present=True, fill=False, roles=[ROLES[i % 5]]) for i in range(10)]
        # First flexible player must leave jungle to the jungle-only player.
        players[0]['roles'] = ['打野', '对抗路']
        slots = match(players, 'fixed')
        self.assertEqual(slots, match(players, 'fixed'))
        self.assertEqual(len({p['id'] for p in slots}), 10)
        for team in ('red', 'blue'):
            self.assertEqual({p['role'] for p in slots if p['team'] == team}, set(ROLES))
        self.assertEqual(next(p for p in slots if p['id'] == '0')['role'], '对抗路')
        players[5]['roles'] = ['打野']
        with self.assertRaises(ValueError):
            match(players, 'infeasible')

    def test_joint_overlap_infeasible_even_with_two_per_role(self):
        # Five flex players cannot cover six slots; others cover only four.
        players = [dict(id=str(i), name=str(i), roles=ROLES[:3] if i < 5 else ROLES[3:], fill=False) for i in range(10)]
        with self.assertRaises(ValueError):
            match(players, 'overlap')

    def test_persistence_rounds_conflicts_and_replacements(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.db'
            state = read_state('demo', path)
            self.assertEqual(read_state('real', path)['players'][0]['roles'], [])
            state = mutate('demo', state['revision'], 'draw', path=path)
            draft = state['draft']
            self.assertEqual(read_state('demo', path)['draft']['id'], draft['id'])
            with self.assertRaises(ValueError):
                mutate('demo', 0, 'draw', path=path)
            before = [p['id'] for p in draft['slots']]
            state = mutate('demo', state['revision'], 'replace', {'id': draft['id'], 'slot': 0}, path)
            self.assertEqual([p['id'] for p in state['draft']['slots']][1:], before[1:])
            self.assertFalse(next(p for p in state['players'] if p['id'] == before[0])['present'])
            state = mutate('demo', state['revision'], 'lock', {'id': draft['id']}, path)
            used = {p['id'] for p in state['history'][0]['slots']}
            self.assertTrue(used.isdisjoint({p['id'] for p in eligible(state)}))
            state = mutate('demo', state['revision'], 'draw', path=path)
            self.assertTrue(used.isdisjoint({p['id'] for p in state['draft']['slots']}))
            with self.assertRaises(ValueError):
                mutate('demo', state['revision'], 'discard', {'id': state['draft']['id']}, path)
            state = mutate('demo', state['revision'], 'discard', {'id': state['draft']['id'], 'reason': '演练'}, path)
            state = mutate('demo', state['revision'], 'next-round', path=path)
            self.assertEqual(state['round'], 2)
            self.assertEqual(len(state['history']), 2)

    def test_full_nine_matches_without_repeats(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.db'
            state = read_state('demo', path)
            seen = set()
            for _ in range(9):
                state = mutate('demo', state['revision'], 'draw', path=path)
                self.assertTrue(seen.isdisjoint(p['id'] for p in state['draft']['slots']))
                seen.update(p['id'] for p in state['draft']['slots'])
                state = mutate('demo', state['revision'], 'lock', {'id': state['draft']['id']}, path)
            self.assertEqual(len(seen), 90)
            self.assertEqual(len(eligible(state)), 1)
            with self.assertRaises(ValueError):
                mutate('demo', state['revision'], 'draw', path=path)


if __name__ == '__main__':
    unittest.main()
