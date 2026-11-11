import unittest
from app.services.annual_match import match_round, ROLES

class SameTeamTests(unittest.TestCase):
    def test_group_preserves_unique_roster_and_roles(self):
        players=[dict(id=str(i),name=f'Player{i}',roles=[ROLES[i%5]],fill=False) for i in range(95)]
        names=['Player0','Player1','Player2']
        placements=set()
        for seed in ['one','two','three']:
            groups=match_round(players,seed,19,False,same_team_names=names)
            teams=[[p for p in game if p['team']==side] for game in groups for side in ['red','blue']]
            teams=[t for t in teams if t]
            self.assertEqual(len(teams),19)
            self.assertEqual(len({p['id'] for t in teams for p in t}),95)
            for t in teams:self.assertEqual({p['role'] for p in t},set(ROLES))
            target=next(i for i,t in enumerate(teams) if names[0] in [p['name'] for p in t])
            self.assertTrue(set(names)<={p['name'] for p in teams[target]})
            placements.add(target)
        self.assertGreater(len(placements),1)

    def test_invalid_group_fails_explicitly(self):
        with self.assertRaises(ValueError):match_round([], 'x',19,True,same_team_names=['missing','also missing'])
