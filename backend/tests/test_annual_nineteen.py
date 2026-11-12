import unittest,tempfile,json,sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from app.services import annual_match as service
from app.services.annual_tournament import bracket,participants

class NineteenTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'event.db'
        self.patch=patch('app.services.annual_match.DB_PATH',self.path);self.patch.start()
        self.state=service.read_state('real')
        self.players=[dict(id=str(i),name=f'选手{i}',present=True,roles=[service.ROLES[i%5]],fill=False,highest_rank='王者') for i in range(95)]
        self.state.update(players=self.players,tournament_settings={'team_count':19,'allow_offrole':True},tournament=bracket(team_count=19))
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE activity SET body=? WHERE mode='real'",(json.dumps(self.state),))
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def command(self,action,payload=None):
        self.state=service.mutate('real',self.state['revision'],action,payload)
        return self.state
    def test_random_second_pairs_ten_winners_once(self):
        self.command('tournament-generate')
        with self.assertRaises(ValueError):self.command('tournament-random-second')
        self.command('tournament-random-pairing')
        for i in range(1,10):self.command('tournament-score',dict(id=f'A{i}',score_a=2,score_b=1))
        self.command('tournament-random-playin')
        self.command('tournament-score',dict(id='P1',score_a=2,score_b=1))
        expected={m['winner'] for m in self.state['tournament']['matches'] if m['stage'] in ['opening','playin']}
        self.command('tournament-random-second')
        t=self.state['tournament'];by_id={m['id']:m for m in t['matches']}
        ids=[by_id[source.split(':')[1]]['winner'] for m in t['matches'] if m['stage']=='second' for source in m['sources']]
        self.assertEqual(len(ids),10);self.assertEqual(set(ids),expected)
        with self.assertRaises(ValueError):self.command('tournament-random-second')

    def test_four_close_winners_pair_and_wait_for_last_seat(self):
        from app.services.annual_nineteen import finalists
        self.command('tournament-generate');self.command('tournament-random-pairing')
        for i in range(1,10):self.command('tournament-score',dict(id=f'A{i}',score_a=2,score_b=1))
        self.command('tournament-random-playin');self.command('tournament-score',dict(id='P1',score_a=2,score_b=0))
        self.command('tournament-random-second')
        for i in range(1,6):self.command('tournament-score',dict(id=f'B{i}',score_a=2,score_b=0 if i==1 else 1))
        protected=next(m['winner'] for m in self.state['tournament']['matches'] if m['id']=='B1')
        with self.assertRaises(ValueError):self.command('tournament-challenge',{'team_ids':[m['winner'] for m in self.state['tournament']['matches'] if m['id'] in ['B2','B3']]})
        self.command('tournament-random-qualifier')
        t=self.state['tournament'];q=[m for m in t['matches'] if m['stage']=='qualifier']
        self.assertEqual(len(q),2);self.assertTrue(all(m['best_of']==3 for m in q))
        self.assertEqual({source for m in q for source in m['sources']},{f'winner:B{i}' for i in range(2,6)})
        with self.assertRaises(ValueError):self.command('tournament-random-qualifier')
        from copy import deepcopy
        before=deepcopy(self.state['tournament'])
        with self.assertRaises(ValueError):self.command('tournament-reset-qualifier',{'reason':' '})
        self.command('tournament-reset-qualifier',{'reason':'测试撤销'})
        reset=self.state['tournament']
        self.assertNotEqual(reset['id'],before['id'])
        self.assertEqual([m for m in reset['matches'] if m['stage'] in ['opening','playin','second']],[m for m in before['matches'] if m['stage'] in ['opening','playin','second']])
        self.assertEqual(reset['teams'],before['teams'])
        self.assertNotIn('qualification_slots',reset)
        self.assertFalse(any(m['id']=='C2' for m in reset['matches']))
        self.assertTrue(any(r['id']==before['id'] and r['reason']=='测试撤销' for r in self.state['team_draw_history']))
        self.command('tournament-random-qualifier')
        with self.assertRaises(ValueError):self.command('tournament-score',dict(id='B1',score_a=2,score_b=1))
        for key in ['C1','C2']:self.command('tournament-score',dict(id=key,score_a=2,score_b=1))
        with self.assertRaises(ValueError):self.command('tournament-reset-qualifier',{'reason':'不允许撤销已计分抽签'})
        entries=finalists(self.state['tournament'])
        self.assertEqual(entries[0],protected);self.assertEqual(len({x for x in entries if x}),3);self.assertIsNone(entries[-1])
        with self.assertRaises(ValueError):self.command('tournament-random-semi')
        with self.assertRaises(ValueError):self.command('tournament-score',dict(id='S1',score_a=1,score_b=0))
        self.command('tournament-public',dict(enabled=True,show_names=False))
        public=service.public_state(self.state['public_view']['token'])['tournament']
        self.assertEqual(public['qualification_mode'],'four-paired');self.assertEqual(public['finalist_team_ids'],entries)

    def test_incremental_95_and_full_bracket(self):
        self.command('tournament-public',{'enabled':True,'draw_enabled':True,'show_names':True})
        token=self.state['public_view']['token']
        for i in range(19):
            self.command('tournament-public-draw',{'token':token})
            self.assertEqual(sum(len(t['players']) for t in self.state['tournament']['teams']), (i+1)*5)
            public=service.public_state(token)['tournament']
            self.assertNotIn('draw_plan',public)
            self.assertFalse(any('highest_rank' in p for t in public['teams'] for p in t['players']))
        t=self.state['tournament'];self.assertEqual(len(t['teams']),19);self.assertEqual(len(t['matches']),19)
        self.assertEqual(len(t['last_draw_team_ids']),1)
        for team in t['teams']:self.assertEqual({p['role'] for p in team['players']},set(service.ROLES))
        with self.assertRaises(ValueError):self.command('tournament-public-draw',{'token':token})
        with self.assertRaises(ValueError):self.command('tournament-challenge')
        with self.assertRaises(ValueError):self.command('tournament-score',dict(id='A1',score_a=2,score_b=0))
        self.assertIsNone(t['bye_team_id'])
        self.assertTrue(all('pending' in source for m in t['matches'] if m['stage']=='opening' for source in m['sources']))
        with self.assertRaises(ValueError):self.command('tournament-bye',{'team_id':'T19'})
        for i in range(9):self.command('tournament-pair',{'id':f'A{i+1}','team_ids':[f'T{i*2+1:02}',f'T{i*2+2:02}']})
        with self.assertRaises(ValueError):self.command('tournament-pair',{'id':'A2','team_ids':['T01','T02']})
        self.command('tournament-bye',{'team_id':'T19'})
        for key in [f'A{i}' for i in range(1,10)]:self.command('tournament-score',dict(id=key,score_a=2,score_b=1))
        t=self.state['tournament']; opening=t['matches'][0]
        loser=next(source.split(':')[1] for source in opening['sources'] if source!='team:'+opening['winner'])
        with self.assertRaises(ValueError):self.command('tournament-playin',{'team_id':opening['winner']})
        self.command('tournament-playin',{'team_id':loser})
        with self.assertRaises(ValueError):self.command('tournament-playin',{'team_id':loser})
        with self.assertRaises(ValueError):self.command('tournament-score',dict(id='A1',score_a=2,score_b=0))
        self.command('tournament-score',dict(id='P1',score_a=2,score_b=0))
        winners=[m['winner'] for m in self.state['tournament']['matches'] if m['stage'] in ['opening','playin']]
        for i in range(5):self.command('tournament-pair',{'id':f'B{i+1}','team_ids':winners[i*2:i*2+2]})
        for i in range(1,6):self.command('tournament-score',dict(id=f'B{i}',score_a=2,score_b=0 if i<=3 else 1))
        chosen=[m['winner'] for m in self.state['tournament']['matches'] if m['id'] in ['B4','B5']]
        with self.assertRaises(ValueError):self.command('tournament-challenge')
        self.command('tournament-challenge',{'team_ids':chosen});self.assertEqual(len(set(self.state['tournament']['qualification_slots'])),2)
        with self.assertRaises(ValueError):self.command('tournament-challenge',{'team_ids':chosen})
        with self.assertRaises(ValueError):self.command('tournament-score',dict(id='B4',score_a=2,score_b=0))
        for key in ['C1','S1','S2','F1']:self.command('tournament-score',dict(id=key,score_a=2 if key=='C1' else 3,score_b=0))
        self.assertEqual(sum(bool(m['winner']) for m in self.state['tournament']['matches']),19)
        with self.assertRaises(ValueError):self.command('tournament-score',dict(id='B1',score_a=0,score_b=2))
    def test_sweep_winners_protected_and_special_cases_pause(self):
        from app.services.annual_nineteen import draw_qualifier,choose_playin
        from copy import deepcopy
        t=bracket(team_count=19)
        for match in t['matches']:
            if match['stage']=='second':match.update(winner='team-'+match['id'],score_a=2,score_b=0 if match['id'] in ['B1','B2','B3'] else 1)
        with self.assertRaises(ValueError):draw_qualifier(t,1,['team-B1','team-B4'])
        with self.assertRaises(ValueError):draw_qualifier(t,1,['team-B4','team-B4'])
        special=deepcopy(t)
        next(m for m in special['matches'] if m['id']=='B4')['score_b']=0
        with self.assertRaisesRegex(ValueError,'特殊'):draw_qualifier(special,1,['team-B4','team-B5'])
        self.assertNotIn('qualification_slots',special)
        for match in t['matches']:
            if match['stage']=='opening':match.update(winner=match['sources'][0].split(':')[1],score_a=2,score_b=0)
        with self.assertRaises(ValueError):choose_playin(t,t['matches'][0]['sources'][1].split(':')[1],1)
        self.assertNotIn('playin_opponent',t)

    def test_minimal_offrole_preserves_all_nineteen_junglers(self):
        self.players[0]['roles']=['游走'];self.players[5]['roles']=['游走'];self.players[3]['roles']=['中路']
        self.assertEqual(service.match_round(self.players,'strict',team_count=19),[])
        for seed in ['one','two','three']:
            groups=service.match_round(self.players,seed,team_count=19,allow_offrole=True)
            slots=[p for group in groups for p in group]
            self.assertEqual(len(slots),95);self.assertEqual(len({p['id'] for p in slots}),95)
            self.assertEqual(sum(p['rank']==20 for p in slots),3)
            junglers=[p for p in slots if p['role']=='打野']
            self.assertEqual(len(junglers),19);self.assertTrue(all(p['rank']==0 for p in junglers))

    def test_random_pairing_and_both_challenges(self):
        self.command('tournament-generate')
        self.command('tournament-random-pairing')
        t=self.state['tournament']
        assigned=[s.split(':')[1] for m in t['matches'] if m['stage']=='opening' for s in m['sources']]+[t['bye_team_id']]
        self.assertEqual(len(set(assigned)),19)
        before=json.dumps(t,sort_keys=True)
        with self.assertRaises(ValueError):self.command('tournament-random-pairing')
        self.assertEqual(json.dumps(service.read_state('real')['tournament'],sort_keys=True),before)
        with self.assertRaises(ValueError):self.command('tournament-random-playin')
        for i in range(1,10):self.command('tournament-score',dict(id=f'A{i}',score_a=2,score_b=1 if i in [2,4] else 0))
        self.command('tournament-random-playin')
        t=self.state['tournament'];p=next(m for m in t['matches'] if m['stage']=='playin')
        self.assertEqual(p['sources'][0],'team:'+t['bye_team_id'])
        self.assertIn(p['sources'][1],['loser:A2','loser:A4'])
        self.assertEqual(t['playin_selection'],'random')
        with self.assertRaises(ValueError):self.command('tournament-random-playin')
        self.command('tournament-score',dict(id='P1',score_a=2,score_b=0))
        winners=[m['winner'] for m in self.state['tournament']['matches'] if m['stage'] in ['opening','playin']]
        for i in range(5):self.command('tournament-pair',dict(id=f'B{i+1}',team_ids=winners[i*2:i*2+2]))
        for i in range(1,6):self.command('tournament-score',dict(id=f'B{i}',score_a=2,score_b=0 if i<=3 else 1))
        self.command('tournament-random-qualifier')
        self.assertEqual(set(self.state['tournament']['qualification_slots']),{'B4','B5'})
        self.assertEqual(self.state['tournament']['qualification_selection'],'random')
        with self.assertRaises(ValueError):self.command('tournament-random-qualifier')

    def test_random_challenge_does_not_select_sweep_or_missing_candidates(self):
        from app.services.annual_nineteen import random_playin,random_qualifier
        t=bracket(team_count=19)
        for m in t['matches']:
            if m['stage'] in ['opening','second']:m.update(winner=m['id'],score_a=2,score_b=0)
        with self.assertRaises(ValueError):random_playin(t,1)
        with self.assertRaises(ValueError):random_qualifier(t,1)
        self.assertNotIn('qualification_slots',t)

    def test_same_team_setting_is_not_public(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            state=service.read_state('real');state['tournament_settings']['same_team_names']=['选手0','选手1','选手2']
            db.execute("UPDATE activity SET body=? WHERE mode='real'",(json.dumps(state),))
        self.command('tournament-public',dict(enabled=True,draw_enabled=True,show_names=True))
        public=service.public_state(self.state['public_view']['token'])
        self.assertNotIn('same_team_names',json.dumps(public))
        self.assertNotIn('tournament_settings',public)

    def test_unstarted_qualifier_is_bo3_and_scored_rules_preserved(self):
        from app.services.annual_nineteen import normalize_unstarted_rules,random_qualifier
        t=bracket(team_count=19)
        qualifier=next(m for m in t['matches'] if m['stage']=='qualifier')
        self.assertEqual(qualifier['best_of'],3)
        qualifier['best_of']=5
        normalize_unstarted_rules(t)
        self.assertEqual(qualifier['best_of'],3)
        qualifier.update(best_of=5,score_a=1)
        normalize_unstarted_rules(t)
        self.assertEqual(qualifier['best_of'],5)
        for m in t['matches']:
            if m['stage']=='second':m.update(winner=m['id'],score_a=2,score_b=0 if m['id']=='B1' else 1)
        with self.assertRaises(ValueError):random_qualifier(t,1)

    def test_random_semis_require_four_teams_and_lock_result(self):
        from app.services.annual_nineteen import random_semis
        t=bracket(team_count=19)
        with self.assertRaises(ValueError):random_semis(t,1)
        t['qualification_slots']=['B4','B5']
        for m in t['matches']:
            if m['stage']=='second' or m['id']=='C1':m['winner']='winner-'+m['id']
        random_semis(t,1)
        slots=[s for m in t['matches'] if m['stage']=='semi' for s in m['sources']]
        self.assertEqual(set(slots),{f'finalist:{i}' for i in range(4)})
        self.assertTrue(t['semi_pairing_drawn'])
        with self.assertRaises(ValueError):random_semis(t,1)

    def test_reset_pairing_preserves_teams_and_history(self):
        from copy import deepcopy
        self.command('tournament-generate');self.command('tournament-random-pairing')
        before=deepcopy(self.state['tournament'])
        with self.assertRaises(ValueError):self.command('tournament-reset-pairing',{'reason':'  '})
        self.command('tournament-reset-pairing',{'reason':'测试重抽'})
        t=self.state['tournament']
        self.assertEqual(t['teams'],before['teams'])
        self.assertNotEqual(t['id'],before['id'])
        self.assertIsNone(t['bye_team_id'])
        self.assertTrue(all('pending' in source for m in t['matches'] if m['stage']=='opening' for source in m['sources']))
        record=next(r for r in self.state['team_draw_history'] if r['id']==before['id'])
        self.assertEqual(record['tournament']['matches'],before['matches'])
        self.assertEqual(record['reason'],'测试重抽')
        self.command('tournament-restore',{'id':before['id']})
        self.assertEqual(self.state['tournament']['matches'],before['matches'])
        self.command('tournament-score',dict(id='A1',score_a=1,score_b=0))
        with self.assertRaises(ValueError):self.command('tournament-reset-pairing',{'reason':'测试重抽'})

if __name__=='__main__':unittest.main()
