import unittest,tempfile,json,sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from app.services import annual_match as service
from app.jobs.migrate_annual_roster import migrate

class RosterMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'event.db'
        self.patch=patch('app.services.annual_match.DB_PATH',self.path);self.patch.start()
        state=service.read_state('real')
        self.state=service.mutate('real',state['revision'],'tournament-public',{'enabled':True,'draw_enabled':True,'show_names':False})
        players=[dict(id=str(i+1),name=f'选手{i}',roles=[],fill=False,present=True) for i in range(95)]
        for i,name in enumerate(['职业选手A','职业选手B']):players[i].update(name=name,roles=['打野'],highest_rank='王者',strength_rank='王者')
        self.payload=dict(version='test95',players=players)
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def test_backup_public_settings_and_idempotence(self):
        settings=self.state['public_view'].copy()
        report=migrate(self.payload)
        self.assertEqual(report['status'],'validated');self.assertEqual(len(service.read_state('real')['players']),91)
        report=migrate(self.payload,True)
        self.assertTrue(Path(report['backup']).is_file())
        after=service.read_state('real')
        self.assertEqual(after['public_view'],settings);self.assertEqual(len(after['players']),95)
        self.assertEqual(after['tournament']['rules_version'],3);self.assertFalse(after['tournament']['generated'])
        self.assertEqual(migrate(self.payload,True)['status'],'already-applied')
    def test_active_scores_abort_without_changes(self):
        self.state['tournament']['matches'][0]['score_a']=1
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE activity SET body=? WHERE mode='real'",(json.dumps(self.state),))
        with self.assertRaisesRegex(ValueError,'Active scores'):migrate(self.payload,True)
        self.assertEqual(len(service.read_state('real')['players']),91)
        self.assertEqual(len(list(self.path.parent.glob('annual_match.before-roster95-*'))),0)

if __name__=='__main__':unittest.main()
