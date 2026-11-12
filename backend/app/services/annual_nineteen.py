"""19-team roster draws with manually assigned matches and qualification."""
from uuid import uuid4
from datetime import datetime, timezone

def bracket19(teams=None, seed='template', actor=None):
    teams = teams or [dict(id=f'T{i:02}', name=chr(64+i), players=[]) for i in range(1,20)]
    bye = None
    matches = []
    def add(key, stage, number, sources, bo=3):
        matches.append(dict(id=key, stage=stage, number=number, sources=sources, best_of=bo, score_a=0, score_b=0, winner=None, bans=[]))
    for i in range(9): add(f'A{i+1}', 'opening', i+1, [f'team:pending-A{i+1}-0', f'team:pending-A{i+1}-1'])
    add('P1', 'playin', 1, ['team:pending-bye', 'loser:pending'], 3)
    for i in range(5): add(f'B{i+1}', 'second', i+1, [f'team:pending-B{i+1}-0',f'team:pending-B{i+1}-1'])
    add('C1', 'qualifier', 1, ['winner:pending1','winner:pending2'], 3)
    for i in range(2): add(f'S{i+1}','semi',i+1,[f'finalist:{i*2}',f'finalist:{i*2+1}'],5)
    add('F1','final',1,['winner:S1','winner:S2'],5)
    return dict(id=uuid4().hex if actor is not None else 'template',generated=False,format='19-10-5-4',rules_version=3,draw_unit='team',seed=seed,teams=teams,matches=matches,reserves=[],bye_team_id=bye,created_by=actor,created_at=datetime.now(timezone.utc).isoformat())

def choose_pair(t, key, team_ids):
    if t.get('draw_plan') or not t.get('generated'): raise ValueError('请先抽齐全部队伍，再填写对阵')
    match=next((m for m in t['matches'] if m['id']==key),None)
    if not match or match['stage'] not in ['opening','second']: raise ValueError('只支持首轮或10进5对阵设置')
    if match['score_a'] or match['score_b']: raise ValueError('已有比分的对局不能重新配对')
    if not team_ids or len(team_ids)!=2 or len(set(team_ids))!=2: raise ValueError('请选择两支不同队伍')
    if match['stage']=='opening':
        candidates={team['id'] for team in t['teams']}
        if t.get('bye_team_id'): candidates.discard(t['bye_team_id'])
    else:
        upstream=[m for m in t['matches'] if m['stage'] in ['opening','playin']]
        if not all(m['winner'] for m in upstream): raise ValueError('请先完成首轮及晋级资格赛')
        candidates={m['winner'] for m in upstream}
    winners={m['id']:m['winner'] for m in t['matches']}
    occupied={source.split(':')[1] if source.startswith('team:') else winners.get(source.split(':')[1]) for m in t['matches'] if m['stage']==match['stage'] and m['id']!=key for source in m['sources']}
    if not set(team_ids)<=candidates or set(team_ids)&occupied: raise ValueError('队伍不符合本轮资格或已在其他对局中安排')
    match['sources']=['team:'+key for key in team_ids] if match['stage']=='opening' else ['winner:'+next(m['id'] for m in upstream if m['winner']==identity) for identity in team_ids]

def choose_bye(t, team_id):
    if t.get('bye_team_id'): raise ValueError('首轮待赛队伍已确认')
    opening=[m for m in t['matches'] if m['stage']=='opening']
    identities={team['id'] for team in t['teams']}
    assigned={source.split(':')[1] for m in opening for source in m['sources'] if source.startswith('team:') and source.split(':')[1] in identities}
    if len(assigned)!=18 or team_id not in identities-assigned: raise ValueError('请先填写9场首轮对阵，再确认剩余的一支待赛队伍')
    t['bye_team_id']=team_id
    next(m for m in t['matches'] if m['id']=='P1')['sources'][0]='team:'+team_id

def choose_playin(t, team_id, actor):
    match = next(m for m in t['matches'] if m['id']=='P1')
    if not t.get('bye_team_id'): raise ValueError('请先确认首轮待赛队伍')
    if t.get('playin_opponent'): raise ValueError('首轮资格赛对手已锁定')
    opening = [m for m in t['matches'] if m['stage']=='opening']
    if not all(m['winner'] for m in opening): raise ValueError('请先完成首轮9场比赛')
    candidates = [m for m in opening if sorted([m['score_a'],m['score_b']])==[1,2]]
    origin = next((m for m in candidates if any(s=='team:'+team_id for s in m['sources']) and m['winner']!=team_id), None)
    if not origin: raise ValueError('请选择一支首轮1:2落败的队伍；没有符合条件的队伍时需另定规则')
    t.update(playin_opponent=team_id,playin_selected_by=actor,playin_selected_at=datetime.now(timezone.utc).isoformat())
    match['sources']=['team:'+t['bye_team_id'],'loser:'+origin['id']]

def draw_qualifier(t, actor, team_ids=None):
    if t.get('qualification_slots'): raise ValueError('四强资格赛队伍已锁定')
    candidates=[m for m in t['matches'] if m['stage']=='second']
    if len(candidates)!=5 or not all(m['winner'] for m in candidates): raise ValueError('请先完成10进5的五场比赛')
    if sum(sorted([m['score_a'],m['score_b']])==[0,2] for m in candidates)>=4:
        raise ValueError('出现4支以上2:0胜队，特殊赛制待定；系统不会自动淘汰2:0胜队')
    if sum(sorted([m['score_a'],m['score_b']])==[1,2] for m in candidates)==4:raise ValueError('四支2:1胜队请使用随机两两配对')
    if not team_ids or len(team_ids)!=2 or len(set(team_ids))!=2: raise ValueError('请手动选择第四名和第五名两支胜队')
    selected=[next((m for m in candidates if m['winner']==team_id),None) for team_id in team_ids]
    if any(m is None or sorted([m['score_a'],m['score_b']])!=[1,2] for m in selected):
        raise ValueError('只能选择2:1胜队，2:0胜队直接晋级，不参加加赛')
    chosen=[m['id'] for m in selected]
    t['qualification_slots']=chosen
    t['qualification_selection']='manual-ranking'
    next(m for m in t['matches'] if m['id']=='C1')['sources']=['winner:'+key for key in chosen]
    t['challenge_drawn_by']=actor
    t['challenge_drawn_at']=datetime.now(timezone.utc).isoformat()

def finalists(t):
    matches={m['id']:m for m in t['matches']}
    if not t.get('qualification_slots'): return []
    if t.get('qualification_mode')=='four-paired':
        return [m['winner'] for m in t['matches'] if m['stage']=='second' and m['id'] not in t['qualification_slots']]+[matches['C1']['winner'],matches['C2']['winner'],None]
    return [matches['C1']['winner']]+[matches[f'B{i}']['winner'] for i in range(1,6) if f'B{i}' not in t['qualification_slots']]


def random_pairing(t, actor):
    import secrets
    if t.get('rules_version') != 3 or not t.get('generated') or t.get('draw_plan'):
        raise ValueError('请先抽齐19支队伍')
    opening = [m for m in t['matches'] if m['stage']=='opening']
    if t.get('bye_team_id') or any(m['score_a'] or m['score_b'] or any(not s.startswith('team:pending') for s in m['sources']) for m in opening):
        raise ValueError('首轮签位已经确定，不能重复抽取或覆盖现有对阵')
    identities = [team['id'] for team in t['teams'] if len(team['players'])==5]
    if len(identities)!=19 or len(set(identities))!=19: raise ValueError('需要19支完整且不同的队伍')
    secrets.SystemRandom().shuffle(identities)
    for i,m in enumerate(opening):choose_pair(t,m['id'],identities[i*2:i*2+2])
    choose_bye(t,identities[-1])
    t.update(pairing_selection='random',pairing_drawn_by=actor,pairing_drawn_at=datetime.now(timezone.utc).isoformat())


def random_playin(t, actor):
    import secrets
    opening=[m for m in t['matches'] if m['stage']=='opening']
    if not all(m['winner'] for m in opening):raise ValueError('请先完成首轮9场比赛')
    candidates=[source.split(':')[1] for m in opening if sorted([m['score_a'],m['score_b']])==[1,2] for source in m['sources'] if source!='team:'+m['winner']]
    if not candidates:raise ValueError('没有首轮1:2败队，特殊情况待定')
    choose_playin(t,secrets.choice(candidates),actor)
    t['playin_selection']='random'


def random_qualifier(t, actor):
    import secrets
    matches=[m for m in t['matches'] if m['stage']=='second']
    if not all(m['winner'] for m in matches):raise ValueError('请先完成10进5的五场比赛')
    candidates=[m['winner'] for m in matches if sorted([m['score_a'],m['score_b']])==[1,2]]
    if t.get('qualification_slots') or any(m['score_a'] or m['score_b'] or m['winner'] for m in t['matches'] if m['stage']=='qualifier'):raise ValueError('四强突围对阵已锁定')
    if len(candidates)==4:
        chosen=[m['id'] for m in matches if m['winner'] in candidates]
        secrets.SystemRandom().shuffle(chosen)
        first=next(m for m in t['matches'] if m['id']=='C1')
        first['sources']=['winner:'+key for key in chosen[:2]]
        second=dict(id='C2',stage='qualifier',number=2,sources=['winner:'+key for key in chosen[2:]],best_of=3,score_a=0,score_b=0,winner=None,bans=[])
        t['matches'].insert(t['matches'].index(first)+1,second)
        t.update(qualification_slots=chosen,qualification_mode='four-paired',qualification_selection='random',challenge_drawn_by=actor,challenge_drawn_at=datetime.now(timezone.utc).isoformat())
        return
    if len(candidates) not in [2,3]:raise ValueError('当前2:1胜队数量需要主办方另定突围安排；系统暂不自动抽取')
    draw_qualifier(t,actor,secrets.SystemRandom().sample(candidates,2))
    t['qualification_selection']='random'


def normalize_unstarted_rules(t):
    if t and t.get('format')=='19-10-5-4':
        for m in t.get('matches',[]):
            if m['stage']=='qualifier' and not (m['score_a'] or m['score_b'] or m['winner']): m['best_of']=3


def random_semis(t, actor):
    import secrets
    semis=[m for m in t['matches'] if m['stage']=='semi']
    if t.get('semi_pairing_drawn') or any(m['score_a'] or m['score_b'] or m['winner'] for m in semis):raise ValueError('四强对阵已锁定，不能重复抽取')
    identities=finalists(t)
    if len(identities)!=4 or not all(identities) or len(set(identities))!=4:raise ValueError('请先决出正式四强')
    slots=list(range(4));secrets.SystemRandom().shuffle(slots)
    for i,m in enumerate(semis):m['sources']=[f'finalist:{key}' for key in slots[i*2:i*2+2]]
    t.update(semi_pairing_drawn=True,semi_pairing_drawn_by=actor,semi_pairing_drawn_at=datetime.now(timezone.utc).isoformat())


def random_second(t, actor):
    import secrets
    upstream=[m for m in t['matches'] if m['stage'] in ['opening','playin']]
    matches=[m for m in t['matches'] if m['stage']=='second']
    if len(upstream)!=10 or not all(m['winner'] for m in upstream):raise ValueError('请先完成首轮及突围挑战赛')
    identities=[m['winner'] for m in upstream]
    if len(set(identities))!=10:raise ValueError('需要10支不同的晋级队伍')
    if len(matches)!=5 or t.get('second_pairing_drawn') or any(m['score_a'] or m['score_b'] or m['winner'] or any(not s.startswith('team:pending') for s in m['sources']) for m in matches):raise ValueError('10进5对阵已确定，不能覆盖')
    secrets.SystemRandom().shuffle(identities)
    for i,m in enumerate(matches):choose_pair(t,m['id'],identities[i*2:i*2+2])
    t.update(second_pairing_drawn=True,second_pairing_drawn_by=actor,second_pairing_drawn_at=datetime.now(timezone.utc).isoformat())
