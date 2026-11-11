"""Backup-first import of the approved 95-player roster; never import local draws."""
import argparse
import copy
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from app.services import annual_match as service
from app.services.annual_tournament import bracket,remember_draw
from app.api.routers.annual_match import Player

def migrate(payload, apply=False):
    incoming=[Player.model_validate(p).model_dump() for p in payload['players']]
    if len(incoming)!=95 or len({p['name'] for p in incoming})!=95: raise ValueError('Expected 95 unique names')
    if any(p['name'] in ['王燕','黄学武'] for p in incoming): raise ValueError('Boss placeholders must be replaced')
    for name in ['职业选手A','职业选手B']:
        p=next(p for p in incoming if p['name']==name)
        if p['roles']!=['打野'] or p['highest_rank']!='王者' or p['strength_rank']!='王者': raise ValueError('Substitute profile mismatch')
    if any(len(set(p['roles']))!=len(p['roles']) or any(r not in service.ROLES for r in p['roles']) for p in incoming): raise ValueError('Invalid role choices')
    state=service.read_state('real')
    current=state['tournament']
    if state.get('roster_import_version')==payload['version'] and len(state['players'])==95 and current.get('rules_version')==3:
        return dict(status='already-applied',revision=state['revision'],players=95)
    if any(m['score_a'] or m['score_b'] for m in current['matches']): raise ValueError('Active scores exist: stop migration without changing data')
    existing={p['name']:p['id'] for p in state['players']}
    aliases={'刘洋洋':'洋洋','韩哲':'韩喆'}
    next_id=max([int(p['id']) for p in state['players'] if str(p['id']).isdigit()]+[0])+1
    for player in incoming:
        identity=existing.get(player['name'],existing.get(aliases.get(player['name'])))
        if identity is None:identity=str(next_id);next_id+=1
        player['id']=identity
    if len({p['id'] for p in incoming})!=95: raise ValueError('Duplicate IDs')
    slots=[p for group in service.match_round(incoming,'release95-validation',team_count=19,allow_offrole=True) for p in group]
    if len(slots)!=95: raise ValueError('Roster cannot fill 19 teams')
    report=dict(status='validated',players=95,teams=19,junglers=sum(p['role']=='打野' for p in slots),offrole=sum(p['rank']==20 for p in slots),revision=state['revision'])
    if not apply:return report
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=service.DB_PATH.with_name('annual_match.before-roster95-'+stamp+'.db')
    with closing(sqlite3.connect(service.DB_PATH)) as source,closing(sqlite3.connect(backup)) as target:source.backup(target)
    with closing(sqlite3.connect(service.DB_PATH,timeout=10)) as db,db:
        db.execute('BEGIN IMMEDIATE')
        live=json.loads(db.execute("SELECT body FROM activity WHERE mode='real'").fetchone()[0])
        if live['revision']!=state['revision']:raise ValueError('Concurrent update; no data changed')
        t=live['tournament']
        remember_draw(live,t)
        if t.get('generated'):
            live.setdefault('tournament_archives',[]).append(copy.deepcopy(t))
            record=next(r for r in live['team_draw_history'] if r['id']==t['id'])
            record.update(status='abandoned',reason='Upgrade to approved 95-player team-only format')
        # Keep production public settings/token, account data, and all existing records.
        live.update(players=incoming,tournament_settings=dict(team_count=19,allow_offrole=True),tournament=bracket(team_count=19),draft=None,batch=None,roster_import_version=payload['version'],revision=live['revision']+1)
        live.setdefault('audit',[]).append(dict(action='release-roster95',at=stamp,count=95,backup=str(backup)))
        db.execute("UPDATE activity SET body=? WHERE mode='real'",(json.dumps(live,ensure_ascii=False),))
    report.update(status='applied',backup=str(backup),revision=live['revision'])
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    print(json.dumps(migrate(json.loads(Path(args.input).read_text(encoding='utf-8')),args.apply),ensure_ascii=False))
