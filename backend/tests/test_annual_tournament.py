import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.deps import get_current_user
from app.api.routers.annual_match import router
from app.services.annual_match import mutate, read_state, ROLES
from app.services.annual_tournament import bracket, participants, update_score, draw_challenger, select_roster


class TournamentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'event.db'

    def tearDown(self):
        self.temp.cleanup()

    def generate(self):
        return mutate('demo', 0, 'tournament-generate', path=self.path, actor=1)

    def test_template_shape_and_all_teams_have_one_entry(self):
        t = bracket()
        self.assertEqual(len(t['teams']), 18)
        self.assertEqual(len(t['matches']), 17)
        self.assertEqual(len([m for m in t['matches'] if m['best_of'] == 5]), 4)
        entrants = [s for m in t['matches'] for s in m['sources'] if s.startswith('team:')]
        self.assertEqual(len(entrants), 18)
        self.assertEqual(len(set(entrants)), 18)
        self.assertFalse(t['generated'])

    def test_generate_teams_and_preserve_legacy_draw(self):
        state = mutate('demo', 0, 'draw', path=self.path)
        draft = copy.deepcopy(state['draft'])
        state = mutate('demo', state['revision'], 'tournament-generate', path=self.path, actor=2)
        t = state['tournament']
        self.assertEqual(state['draft'], draft)
        self.assertEqual(len(t['teams']), 18)
        players = [p for team in t['teams'] for p in team['players']]
        self.assertEqual(len({p['id'] for p in players}), 90)
        self.assertEqual(len(t['reserves']), 1)
        for team in t['teams']:
            self.assertEqual({p['role'] for p in team['players']}, set(ROLES))
        self.assertEqual(read_state('demo', self.path)['tournament']['seed'], t['seed'])
        with self.assertRaises(ValueError):
            mutate('demo', state['revision'], 'tournament-generate', path=self.path)

    def test_unknown_positions_and_insufficient_attendance_do_not_generate(self):
        real = mutate('real', 0, 'tournament-generate', path=self.path)
        self.assertEqual(len(real['tournament']['teams']), 18)
        state = read_state('demo', self.path)
        state['players'][0]['present'] = False
        state['players'][1]['present'] = False
        state = mutate('demo', 0, 'save', {'players': state['players']}, self.path)
        with self.assertRaises(ValueError):
            mutate('demo', state['revision'], 'tournament-generate', path=self.path)

    def test_demo_roster_isolated_from_legacy_attendance_and_real_mode(self):
        state = read_state('demo', self.path)
        state['players'][0].update(present=False, roles=[])
        state = mutate('demo', 0, 'save', {'players': state['players']}, self.path)
        before = copy.deepcopy(state['players'])
        state = mutate('demo', state['revision'], 'tournament-generate', {'simulation': True}, self.path)
        self.assertEqual(state['players'], before)
        self.assertEqual(len(state['tournament']['teams']), 18)
        self.assertTrue(state['tournament']['simulated_roster'])
        with self.assertRaises(ValueError):
            mutate('real', 0, 'tournament-generate', {'simulation': True}, self.path)

    def test_score_progression_and_best_of_five(self):
        t = self.generate()['tournament']
        with self.assertRaises(ValueError):
            update_score(t, 'S1', 3, 0, 1)
        for m in t['matches']:
            if m['stage'] == 'qualifier':
                draw_challenger(t, 1)
            if m['best_of'] == 5:
                update_score(t, m['id'], 2, 0, 1)
                self.assertIsNone(m['winner'])
                self.assertTrue(all(participants(t, m)))
            update_score(t, m['id'], m['best_of'] // 2 + 1, 1, 1)
            self.assertIsNotNone(m['winner'])
        self.assertEqual(len([m for m in t['matches'] if m['winner']]), 17)
        self.assertIn(t['matches'][-1]['winner'], {team['id'] for team in t['teams']})

    def test_invalid_scores_and_downstream_correction(self):
        t = self.generate()['tournament']
        for scores in [(2, 2), (-1, 0), (3, 0), (True, 0)]:
            with self.assertRaises(ValueError):
                update_score(t, 'A1', *scores, 1)
        for m in t['matches'][:9]:
            update_score(t, m['id'], 2, 0, 1)
        parent = next(m for m in t['matches'] if m['id'] == 'B1')['sources'][0].split(':')[1]
        update_score(t, 'B1', 1, 0, 1)
        with self.assertRaises(ValueError):
            update_score(t, parent, 0, 2, 1)
        update_score(t, parent, 2, 1, 1)
        update_score(t, 'B1', 0, 0, 1)
        update_score(t, parent, 0, 2, 1)

    def test_bans_only_after_top_four_and_no_duplicate_heroes(self):
        t = self.generate()['tournament']
        with self.assertRaises(ValueError):
            update_score(t, 'A1', 0, 0, 1, [dict(game=1, red=['李白'], blue=[])])
        for m in t['matches']:
            if m['stage'] in ('semi', 'final'):
                continue
            if m['stage'] == 'qualifier':
                draw_challenger(t, 1)
            update_score(t, m['id'], m['best_of'] // 2 + 1, 0, 1)
        update_score(t, 'S1', 0, 0, 1, [dict(game=1, red=[' 李白 '], blue=['镜'])])
        semi = next(m for m in t['matches'] if m['id'] == 'S1')
        self.assertEqual(semi['bans'][0]['red'], ['李白'])
        with self.assertRaises(ValueError):
            update_score(t, 'S1', 0, 0, 1, [dict(game=1, red=['李白'], blue=[' 李白 '])])

    def test_demo_finishes_all_and_optimistic_revision(self):
        state = self.generate()
        with self.assertRaises(ValueError):
            mutate('demo', 0, 'tournament-demo', path=self.path)
        state = mutate('demo', state['revision'], 'tournament-demo', path=self.path)
        self.assertEqual(len([m for m in state['tournament']['matches'] if m['winner']]), 17)
        champion = state['tournament']['matches'][-1]['winner']
        state = mutate('demo', state['revision'], 'tournament-demo', path=self.path)
        self.assertEqual(state['tournament']['matches'][-1]['winner'], champion)

    def test_random_challenge_is_locked_and_four_unique_qualifiers(self):
        t = self.generate()['tournament']
        with self.assertRaises(ValueError):
            draw_challenger(t, 1)
        for m in t['matches'][:13]:
            update_score(t, m['id'], 2, 0, 1)
        draw_challenger(t, 1)
        with self.assertRaises(ValueError):
            draw_challenger(t, 1)
        c = next(m for m in t['matches'] if m['id'] == 'C1')
        waiting = participants(t, c)[0]
        update_score(t, 'C1', 3, 1, 1)
        four = [team for m in t['matches'] if m['stage'] == 'semi' for team in participants(t, m)]
        self.assertEqual(len(set(four)), 4)
        self.assertIn(waiting, four)
        challenged = next(m for m in t['matches'] if m['id'] == t['challenge_slot'])
        self.assertNotIn(challenged['winner'], four)
        with self.assertRaises(ValueError):
            update_score(t, challenged['id'], 0, 2, 1)

    def test_roster_lottery_independent_of_preference_cost(self):
        pool = [dict(id=str(i), name=str(i), roles=[], fill=False) for i in range(91)]
        roster, audit = select_roster(pool, 'fair')
        larger = pool + [dict(id='91', name='91', roles=[], fill=False)]
        large_roster, large_audit = select_roster(larger, '92-players')
        self.assertEqual(len(large_roster), 90)
        self.assertEqual(len(large_audit['reserve_ids']), 2)
        excluded = audit['reserve_ids'][0]
        pool[int(excluded)]['roles'] = ['对抗路']
        again, second = select_roster(pool, 'fair')
        self.assertEqual(audit['reserve_ids'], second['reserve_ids'])
        self.assertEqual(len(roster), 90)
        self.assertEqual({p['id'] for p in roster}, {p['id'] for p in again})

    def test_roster_lottery_adjusts_only_for_feasibility(self):
        roles = ['对抗路', '打野', '中路', '发育路', '游走']
        pool = [dict(id=str(i), name=str(i), roles=[roles[i % 5]], fill=False) for i in range(91)]
        for seed in ('one', 'two', 'three'):
            roster, audit = select_roster(pool, seed)
            self.assertEqual(pool[int(audit['reserve_ids'][0])]['roles'], ['对抗路'])
            self.assertTrue(all(sum(p['roles'] == [r] for p in roster) == 18 for r in roles))
        pool = [dict(id=str(i), name=str(i), roles=['对抗路'], fill=False) for i in range(90)]
        with self.assertRaises(ValueError): select_roster(pool, 'impossible')

    def test_api_tournament_commands_and_guards(self):
        app = FastAPI()
        app.include_router(router, prefix='/api/v1')
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=3, role=SimpleNamespace(is_active=True, permissions=[SimpleNamespace(code='system.users.manage')]))
        with patch('app.services.annual_match.DB_PATH', self.path):
            client = TestClient(app)
            self.assertEqual(client.post('/api/v1/annual-match/demo/tournament-score', json={'revision': 0, 'id': 'A1', 'score_a': 2, 'score_b': 0}).status_code, 409)
            response = client.post('/api/v1/annual-match/demo/tournament-generate', json={'revision': 0})
            self.assertEqual(response.status_code, 200)
            response = client.post('/api/v1/annual-match/demo/tournament-score', json={'revision': 1, 'id': 'A1', 'score_a': 2, 'score_b': 1})
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(response.json()['data']['tournament']['matches'][0]['winner'])
            self.assertEqual(client.post('/api/v1/annual-match/demo/tournament-score', json={'revision': 2, 'id': 'S1', 'score_a': 3, 'score_b': 3}).status_code, 409)


if __name__ == '__main__':
    unittest.main()
