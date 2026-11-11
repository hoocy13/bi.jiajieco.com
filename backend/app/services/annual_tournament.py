"""An eighteen-team knockout bracket, independent of legacy draw rehearsals."""
import copy
import random
from itertools import combinations
from datetime import datetime, timezone
from uuid import uuid4


def bracket(teams=None, seed='template', actor=None, team_count=18):
    if team_count == 19 or teams and len(teams) == 19:
        from app.services.annual_nineteen import bracket19
        return bracket19(teams, seed, actor)
    teams = teams or [dict(id=f'T{i:02}', name=chr(64 + i), players=[]) for i in range(1, 19)]
    order = [t['id'] for t in teams]
    random.Random(seed).shuffle(order)
    matches = []

    def add(key, stage, number, sources, best_of=3):
        matches.append(dict(id=key, stage=stage, number=number, sources=sources,
                            best_of=best_of, score_a=0, score_b=0, winner=None, bans=[]))

    for i in range(9):
        add(f'A{i+1}', 'opening', i + 1, ['team:' + t for t in order[i*2:i*2+2]])
    entries = [f'winner:A{i+1}' for i in range(9)]
    random.Random(seed + '-second').shuffle(entries)
    for i in range(4):
        add(f'B{i+1}', 'second', i + 1, entries[i*2:i*2+2])
    add('C1', 'qualifier', 1, [entries[8], 'challenger:pending'], 5)
    for i in range(2):
        add(f'S{i+1}', 'semi', i + 1, [f'qualified:B{i*2+1}', f'qualified:B{i*2+2}'], 5)
    add('F1', 'final', 1, ['winner:S1', 'winner:S2'], 5)
    return dict(id=uuid4().hex if actor is not None else 'template', generated=False,
                format='18-9-4-wildcard', seed=seed, teams=teams, matches=matches, reserves=[], created_by=actor,
                created_at=datetime.now(timezone.utc).isoformat())


def participants(tournament, match):
    matches = {m['id']: m for m in tournament['matches']}
    def resolve(source):
        kind, key = source.split(':', 1)
        if kind == 'team':
            return key if any(t['id']==key for t in tournament['teams']) else None
        if kind == 'loser':
            match=matches.get(key)
            if not match or not match['winner']: return None
            return next((source.split(':')[1] for source in match['sources'] if source.startswith('team:') and source!='team:'+match['winner']),None)
        if kind == 'finalist':
            from app.services.annual_nineteen import finalists
            entries = finalists(tournament)
            return entries[int(key)] if entries else None
        if kind == 'challenger':
            return matches[tournament['challenge_slot']]['winner'] if tournament.get('challenge_slot') else None
        if kind == 'qualified':
            if not matches['C1']['winner']:
                return None
            return matches['C1']['winner'] if key == tournament.get('challenge_slot') else matches[key]['winner']
        return matches.get(key, {}).get('winner')
    return [resolve(source) for source in match['sources']]


def draw_challenger(tournament, actor):
    if tournament.get('challenge_slot'):
        raise ValueError('资格赛对手已抽定，不能重复抽签')
    candidates = [m for m in tournament['matches'] if m['stage'] == 'second']
    if len(candidates) != 4 or not all(m['winner'] for m in candidates):
        raise ValueError('请先完成第二轮4场比赛')
    tournament['challenge_slot'] = random.SystemRandom().choice(candidates)['id']
    tournament['challenge_drawn_by'] = actor
    tournament['challenge_drawn_at'] = datetime.now(timezone.utc).isoformat()


def update_score(tournament, key, score_a, score_b, actor, bans=None):
    match = next((m for m in tournament['matches'] if m['id'] == key), None)
    if match is None:
        raise ValueError('找不到该场比赛')
    sides = participants(tournament, match)
    if not all(sides):
        raise ValueError('上游比赛尚未结束，暂不能录入本场比分')
    target = match['best_of'] // 2 + 1
    if any(type(score) is not int or not 0 <= score <= target for score in (score_a, score_b)):
        raise ValueError(f'本场比分须为 0 至 {target} 的整数')
    if score_a == target and score_b == target:
        raise ValueError('双方不能同时达到获胜局数')
    winner = sides[0] if score_a == target else sides[1] if score_b == target else None
    if tournament.get('rules_version',0) >= 2:
        playin = next((m for m in tournament['matches'] if m['id']=='P1'), {})
        selected_loser = 'loser:'+key in playin.get('sources', [])
        if (key in tournament.get('qualification_slots', []) or selected_loser) and (winner != match['winner'] or sorted([score_a,score_b]) != [1,2]):
            raise ValueError('加赛对阵已锁定，不能把已选队伍改为不符合1:2败队或2:1胜队条件的结果')
    if winner != match['winner']:
        affected = {key}
        for child in tournament['matches']:
            dependencies = {source.split(':', 1)[1] for source in child['sources'] if not source.startswith('team:')}
            if child['stage'] == 'qualifier' and tournament.get('challenge_slot'):
                dependencies.add(tournament['challenge_slot'])
            if child['stage'] == 'semi':
                dependencies.add('C1')
                if tournament['format'] == '19-10-5-4': dependencies.update(f'B{i}' for i in range(1,6))
            if dependencies & affected:
                affected.add(child['id'])
                if child['score_a'] or child['score_b']:
                    raise ValueError('后续比赛已有比分，不能改变本场晋级队伍，请先清除下游比分')
    if bans is not None:
        seen_games = set()
        bans = copy.deepcopy(bans)
        for game in bans:
            game['red'] = [name.strip() for name in game['red']]
            game['blue'] = [name.strip() for name in game['blue']]
            if match['best_of'] != 5 and (game['red'] or game['blue']):
                raise ValueError('四强前不启用赛事 Ban')
            if game['game'] in seen_games or not 1 <= game['game'] <= match['best_of']:
                raise ValueError('Ban 的局号重复或超出赛制范围')
            seen_games.add(game['game'])
            heroes = game['red'] + game['blue']
            if any(not name.strip() or len(name) > 30 for name in heroes) or len(set(heroes)) != len(heroes):
                raise ValueError('同一小局的禁用英雄不能留空或重复')
        match['bans'] = copy.deepcopy(bans)
    match.setdefault('score_history', []).append(dict(before=[match['score_a'], match['score_b']],
                                                     after=[score_a, score_b], actor=actor,
                                                     at=datetime.now(timezone.utc).isoformat()))
    match.update(score_a=score_a, score_b=score_b, winner=winner,
                 updated_by=actor, updated_at=datetime.now(timezone.utc).isoformat())


def select_roster(pool, seed):
    """Uniform random reserve combination among feasible 90-player rosters.

    With at most two reserves there are at most C(92,2)=4186 combinations.
    Hall's capacity condition on the five roles checks feasibility without
    allowing position-preference costs to choose the participants.
    """
    roles = ['对抗路', '打野', '中路', '发育路', '游走']
    masks = {p['id']: 31 if not p['roles'] or p['fill'] else sum(1 << roles.index(r) for r in p['roles']) for p in pool}
    options = list(combinations(range(len(pool)), len(pool) - 90))
    random.Random(seed + '-roster').shuffle(options)
    for attempt, reserves in enumerate(options):
        excluded = set(reserves)
        roster = [p for i, p in enumerate(pool) if i not in excluded]
        counts = [0] * 32
        for p in roster:
            counts[masks[p['id']]] += 1
        # Players restricted to a subset cannot exceed its 18 slots per role.
        feasible = all(sum(counts[m] for m in range(1, 32) if m & subset == m) <= 18 * subset.bit_count() for subset in range(1, 32))
        if feasible:
            return roster, dict(rule='random-roster-then-positions-v2',
                                initial_reserve_ids=[pool[i]['id'] for i in options[0]],
                                reserve_ids=[pool[i]['id'] for i in reserves],
                                adjusted_for_positions=attempt > 0, checked_combinations=attempt + 1)
    raise ValueError('当前位置限制无法组成18队，请增加可玩位置或确认补位意愿')


def remember_draw(state, tournament):
    if not tournament or not tournament.get('generated'):
        return
    history = state.setdefault('team_draw_history', [])
    record = next((r for r in history if r['id'] == tournament['id']), None)
    if record:
        record['tournament'] = copy.deepcopy(tournament)
    else:
        history.append(dict(id=tournament['id'], created_at=tournament['created_at'],
                            created_by=tournament.get('created_by'), tournament=copy.deepcopy(tournament)))
    state['team_draw_history'] = history[-5:]


def mutate_tournament(state, action, payload, actor, mode, matcher):
    existing = state.get('tournament')
    if action == 'tournament-public':
        if mode != 'real':
            raise ValueError('模拟演练不能公开')
        if payload.get('enabled') and (existing and (existing.get('simulated_results') or existing.get('simulated_roster')) or (not existing or not existing.get('generated')) and not payload.get('draw_enabled')):
            raise ValueError('请先生成正式队伍，模拟数据不能公开')
        settings = state.setdefault('public_view', {})
        settings.setdefault('token', uuid4().hex)
        settings.update(enabled=bool(payload.get('enabled')), show_names=bool(payload.get('show_names')), draw_enabled=bool(payload.get('draw_enabled')),
                        updated_at=datetime.now(timezone.utc).isoformat(), updated_by=actor)
        return
    if action == 'tournament-abandon':
        if not existing or not existing.get('generated'):
            raise ValueError('当前没有可放弃的抽选')
        reason = payload.get('reason', '').strip()
        if not reason:
            raise ValueError('请填写放弃原因')
        remember_draw(state, existing)
        record = next(r for r in state['team_draw_history'] if r['id'] == existing['id'])
        record.update(status='abandoned', reason=reason, abandoned_by=actor,
                      abandoned_at=datetime.now(timezone.utc).isoformat())
        state['tournament'] = bracket(team_count=state.get('tournament_settings', {}).get('team_count', 18))
        if not state.get('public_view', {}).get('draw_enabled') and state.get('public_view'):
            state['public_view']['enabled'] = False
        return
    if action == 'tournament-restore':
        if existing and any(m['score_a'] or m['score_b'] for m in existing['matches']):
            raise ValueError('当前赛事已有比分，不能恢复其他抽签')
        record = next((r for r in state.get('team_draw_history', []) if r['id'] == payload.get('id')), None)
        if not record:
            raise ValueError('抽签记录不存在或已超出最近5次')
        remember_draw(state, existing)
        state['tournament'] = copy.deepcopy(record['tournament'])
        return
    if action == 'tournament-public-draw':
        import secrets
        settings = state.get('public_view', {})
        if mode != 'real' or not settings.get('enabled') or not settings.get('draw_enabled') or not secrets.compare_digest(settings.get('token', ''), payload.get('token', '')):
            raise ValueError('公开抽队功能未开启或链接已失效')
        if existing and existing.get('generated') and 'draw_plan' not in existing:
            raise ValueError('队伍抽签已完成，如需重新抽选请先放弃本次抽选')
        if not existing or not existing.get('generated'):
            mutate_tournament(state, 'tournament-generate', payload, actor, mode, matcher)
            existing = state['tournament']
            existing['draw_plan'] = copy.deepcopy(existing['teams'])
            existing['drawn_matches'] = 0
            if len(existing['teams']) == 18:
                for i, match in enumerate(existing['matches'][:9]):
                    match['sources'] = [f'team:T{i*2+1:02}', f'team:T{i*2+2:02}']
            for team in existing['teams']: team['players'] = []
        count = existing['drawn_matches']
        if existing.get('draw_unit') == 'team':
            team=next((t for t in existing['teams'] if not t['players']),None)
            if not team: raise ValueError('所有队伍已抽齐')
            ids=[team['id']]
            existing['drawn_teams']=count+1
        else:
            ids = [source.split(':')[1] for source in existing['matches'][count]['sources']] if count < 9 else [existing['bye_team_id']]
        existing['last_draw_team_ids'] = ids
        for identity in ids:
            team = next(t for t in existing['draw_plan'] if t['id'] == identity)
            existing['teams'][next(i for i,t in enumerate(existing['teams']) if t['id'] == identity)] = copy.deepcopy(team)
        existing['drawn_matches'] = count + 1
        total=len(existing['teams']) if existing.get('draw_unit')=='team' else (10 if len(existing['teams']) == 19 else 9)
        if count + 1 == total: del existing['draw_plan']
        remember_draw(state, existing)
        return
    if action == 'tournament-upgrade':
        if existing and existing.get('format') == '18-9-4-wildcard':
            raise ValueError('当前已是新赛制')
        if existing and existing.get('generated'):
            state.setdefault('tournament_archives', []).append(copy.deepcopy(existing))
            replacement = bracket(copy.deepcopy(existing['teams']), uuid4().hex, actor)
            for field in ('generated', 'reserves', 'snapshot', 'simulated_roster'):
                if field in existing:
                    replacement[field] = copy.deepcopy(existing[field])
            state['tournament'] = replacement
        else:
            state['tournament'] = bracket(team_count=state.get('tournament_settings', {}).get('team_count', 18))
        return
    if action == 'tournament-generate':
        if existing and existing.get('generated'):
            raise ValueError('18队和签位已生成，请在现有赛程中记录比赛结果')
        simulated_roster = bool(payload.get('simulation'))
        if simulated_roster and mode != 'demo':
            raise ValueError('模拟阵容仅适用于演练模式')
        pool = copy.deepcopy([p for p in state['players'] if p['present'] or simulated_roster])
        if simulated_roster:
            roles = ['对抗路', '打野', '中路', '发育路', '游走']
            for i, player in enumerate(pool):
                player.update(present=True, roles=[roles[i % 5]], fill=False)
        team_count = state.get('tournament_settings', {}).get('team_count', 18)
        if team_count == 19 and len(pool) != 95: raise ValueError('19队需要95名到场人员')
        if team_count == 18 and not 90 <= len(pool) <= 92:
            raise ValueError(f'18队需要90名上场人员及最多2名替补，当前到场{len(pool)}人')
        seed = uuid4().hex
        if team_count == 19:
            roster, selection = pool, dict(rule='95-full-roster-jungle-first')
            groups = matcher(roster, seed, team_count=19, allow_offrole=state.get('tournament_settings', {}).get('allow_offrole', False), **({'same_team_names': state['tournament_settings']['same_team_names']} if state.get('tournament_settings', {}).get('same_team_names') else {}))
        else:
            roster, selection = select_roster(pool, seed)
            groups = matcher(roster, seed)
        if len(groups) != (team_count + 1) // 2:
            raise ValueError('当前位置配置无法组成18支完整队伍，请补齐位置或确认补位意愿')
        teams = []
        for slots in groups:
            for side in ('red', 'blue'):
                i = len(teams) + 1
                members = [dict(p) for p in slots if p['team'] == side]
                if not members: continue
                for member in members:
                    member.pop('team', None)
                teams.append(dict(id=f'T{i:02}', name=chr(64 + i), players=members))
        tournament = bracket(teams, seed, actor)
        tournament['generated'] = True
        tournament['simulated_roster'] = simulated_roster
        selected = {p['id'] for team in teams for p in team['players']}
        tournament['reserves'] = [p for p in pool if p['id'] not in selected]
        tournament['snapshot'] = pool
        tournament['roster_selection'] = selection
        state['tournament'] = tournament
        remember_draw(state, tournament)
        return
    if not existing or not existing.get('generated'):
        raise ValueError('请先生成18支队伍和赛程')
    if action == 'tournament-rename':
        name = (payload.get('name') or '').strip()
        team = next((t for t in existing['teams'] if t['id'] == payload.get('team_id')), None)
        if not team or not name or len(name) > 20:
            raise ValueError('请选择队伍并填写1至20字队名')
        name = name[0].upper() + name[1:]
        if any(t['id'] != team['id'] and t['name'].casefold() == name.casefold() for t in existing['teams']):
            raise ValueError('队伍名称不能重复')
        team['name'] = name
        if existing.get('draw_plan'):
            next(t for t in existing['draw_plan'] if t['id'] == team['id'])['name'] = name
        return
    if action in ['tournament-pair','tournament-bye']:
        if existing.get('rules_version')!=3: raise ValueError('当前版本不支持手动安排常规对阵')
        from app.services.annual_nineteen import choose_pair,choose_bye
        if action=='tournament-pair': choose_pair(existing,payload.get('id'),payload.get('team_ids'))
        else: choose_bye(existing,payload.get('team_id'))
        return
    if action == 'tournament-playin':
        if existing['format']!='19-10-5-4': raise ValueError('当前不是19队赛制')
        from app.services.annual_nineteen import choose_playin
        choose_playin(existing, payload.get('team_id'), actor)
        return
    if action == 'tournament-challenge' and existing['format'] == '19-10-5-4':
        from app.services.annual_nineteen import draw_qualifier
        draw_qualifier(existing, actor, payload.get('team_ids'))
        return
    if action == 'tournament-challenge':
        if existing.get('challenge_slot'):
            raise ValueError('资格赛对手已锁定，不能重复选择')
        candidates = [m for m in existing['matches'] if m['stage'] == 'second']
        if len(candidates) != 4 or not all(m['winner'] for m in candidates):
            raise ValueError('请先完成第二轮4场比赛')
        opponent = next((m for m in candidates if m['winner'] == payload.get('team_id')), None)
        if not opponent:
            raise ValueError('请选择4支暂晋级队中的一支')
        existing.update(challenge_slot=opponent['id'], challenge_team_id=opponent['winner'],
                        challenge_selection='manual', challenge_drawn_by=actor,
                        challenge_drawn_at=datetime.now(timezone.utc).isoformat())
    elif action == 'tournament-score':
        if existing.get('draw_plan'):
            raise ValueError('请先抽齐全部队伍')
        update_score(existing, payload.get('id'), payload.get('score_a'), payload.get('score_b'), actor, payload.get('bans'))
    elif action == 'tournament-demo':
        if mode != 'demo':
            raise ValueError('模拟比分仅适用于演练模式')
        rng = random.Random(uuid4().hex)
        for match in existing['matches']:
            if match['winner']:
                continue
            if match['stage'] == 'qualifier' and not existing.get('challenge_slot'):
                draw_challenger(existing, actor)
            target = match['best_of'] // 2 + 1
            # Preserve an already recorded lead, and finish the series legally.
            winner_side = rng.randrange(2)
            scores = [match['score_a'], match['score_b']]
            scores[winner_side] = target
            update_score(existing, match['id'], *scores, actor)
        existing['simulated_results'] = True
    else:
        raise ValueError('未知赛事操作')
