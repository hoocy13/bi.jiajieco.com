"""Local annual-event storage and constrained 5v5 matching. No ODS access."""
import copy
import json
import os
import random
import sqlite3
import secrets
from collections import deque
from contextlib import closing
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from app.services.annual_tournament import bracket, mutate_tournament, remember_draw

ROLES = ['对抗路', '打野', '中路', '发育路', '游走']
NAMES = '付梦瑶 王贺 邹芸 卢婷娟 邵曼宇 李存杰 万子漪 蔡玮琪 陈传英 王小伟 李小刚 吴肖肖 李子一 张露文 何瑞 吕二建 吕畅 陶开 肖红梅 马瑞华 李浩 朱云 殷琦 张婷婷 范雪 孔玲 张进 袁野 王昌顺 严伊民 蒋华锋 姚雨锋 赵岩 祁金晶 黄俊荣 谢煜婷 赵思琪 姜龙俊 章迪妮 魏雪磊 王超 方乐康 刘芳 苏钰靖 陈华恩 樊婧祎 刘确桂 许皓虹 努尔 洋洋 秦冉 李丹 袁清萍 陈慧玲 韩喆 王伟 蒋金玲 冯子轩 华子杭 刘茂源 许晓庆 许文豪 史晨 王舒娴 陈汪月 张怀宽 魏冉 李显 王亚伟 王亚恒 朱鹏举 陈金 王龙 李文琪 宋洁立 郑力玮 张志宏 李宝 张赫鑫 郭亚涛 唐军 黄向东 李佳阳 陈睛睛 刚闯 马兆刚 马一凡 黄郑 章林 毛茁臣 贾玉明'.split()
DB_PATH = Path(os.environ.get('ANNUAL_MATCH_DB_PATH', str(Path(__file__).resolve().parents[2] / 'annual_match.db')))


def initial_state(mode):
    return dict(revision=0, round=1, draft=None, history=[], players=[
        dict(id=str(i + 1), name=name, present=True, roles=[ROLES[i % 5]] if mode == 'demo' else [], fill=False)
        for i, name in enumerate(NAMES)
    ])


def eligible(state):
    played = {p['id'] for m in state['history'] if m['status'] == 'locked' and m['round'] == state['round'] for p in m['slots']}
    return [p for p in state['players'] if p['present'] and p['id'] not in played]


def match(players, seed):
    """DP over ten slots: exact feasibility, then ranked preferences, then random ties."""
    rng = random.Random(seed)
    players = copy.deepcopy(players)
    rng.shuffle(players)
    dp = {0: (0, [])}
    for p in players:
        next_dp = dict(dp)
        for mask, (cost, slots) in dp.items():
            for slot in range(10):
                role = ROLES[slot % 5]
                if mask & (1 << slot) or (p['roles'] and role not in p['roles'] and not p['fill']):
                    continue
                rank = p['roles'].index(role) if role in p['roles'] else (11 if not p['roles'] else 10)
                # The total random contribution is < 1; preference always dominates.
                score = cost + p.get('round_penalty', 0) + rank + rng.random() / 11
                target = mask | (1 << slot)
                if target not in next_dp or score < next_dp[target][0]:
                    assignment = dict(id=p['id'], name=p['name'], role=role, team='red' if slot < 5 else 'blue', rank=rank)
                    next_dp[target] = (score, slots + [(slot, assignment)])
        dp = next_dp
    if 1023 not in dp:
        coverage = {r: sum((not p['roles'] or r in p['roles'] or p['fill']) for p in players) for r in ROLES}
        raise ValueError('无法组成完整两队，请补齐位置或确认补位意愿。各位置可用人数：' + '、'.join(f'{r} {n}人' for r, n in coverage.items()) + '（多位置人员不能重复使用）')
    return [p for _, p in sorted(dp[1023][1])]


def read_state(mode, path=None):
    with closing(sqlite3.connect(path or DB_PATH, timeout=10)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS activity (mode TEXT PRIMARY KEY, body TEXT NOT NULL)')
        db.execute('INSERT OR IGNORE INTO activity VALUES (?, ?)', (mode, json.dumps(initial_state(mode), ensure_ascii=False)))
        state = json.loads(db.execute('SELECT body FROM activity WHERE mode=?', (mode,)).fetchone()[0])
        if not state.get('tournament'):
            state['tournament'] = bracket(team_count=state.get('tournament_settings', {}).get('team_count', 18))
        for i, team in enumerate(state['tournament']['teams']):
            team.setdefault('name', chr(65 + i))
        return state


def match_round(players, seed, team_count=None, allow_offrole=False):
    """Maximize complete matches globally, then optimize position preferences.

    Each role needs two players per match. A min-cost residual network handles
    overlapping role choices without a greedy early match starving later ones.
    """
    players = copy.deepcopy(players)
    rng = random.Random(seed)
    rng.shuffle(players)
    for teams_count in ([team_count] if team_count else range(len(players) // 10 * 2, 0, -2)):
        games = (teams_count + 1) // 2
        source = 0
        role_base = len(players) + 1
        sink = role_base + 5
        graph = [[] for _ in range(sink + 1)]

        def edge(start, end, capacity, cost):
            forward = [end, len(graph[end]), capacity, cost]
            backward = [start, len(graph[start]), 0, -cost]
            graph[start].append(forward)
            graph[end].append(backward)
            return forward

        assignments = []
        for i, player in enumerate(players):
            edge(source, i + 1, 1, 0)
            for r, role in enumerate(ROLES):
                if player['roles'] and role not in player['roles'] and not player['fill'] and not allow_offrole:
                    continue
                rank = player['roles'].index(role) if role in player['roles'] else (11 if not player['roles'] else 10 if player['fill'] else 20)
                cost = (player.get('round_penalty', 0) + rank) * 100000 + rng.randrange(100)
                if rank == 20: cost += 10000000
                if role == '打野' and role not in player['roles']: cost += 100000000
                assignments.append((player, r, rank, edge(i + 1, role_base + r, 1, cost)))
        for r in range(5):
            edge(role_base + r, sink, teams_count, 0)

        flow = 0
        while flow < teams_count * 5:
            distance = [float('inf')] * len(graph)
            previous = [None] * len(graph)
            distance[source] = 0
            queue = deque([source])
            queued = {source}
            while queue:
                start = queue.popleft()
                queued.remove(start)
                for index, item in enumerate(graph[start]):
                    end, _, capacity, cost = item
                    if capacity and distance[start] + cost < distance[end]:
                        distance[end] = distance[start] + cost
                        previous[end] = (start, index)
                        if end not in queued:
                            queue.append(end)
                            queued.add(end)
            if previous[sink] is None:
                break
            end = sink
            while end != source:
                start, index = previous[end]
                item = graph[start][index]
                item[2] -= 1
                graph[end][item[1]][2] += 1
                end = start
            flow += 1
        if flow != teams_count * 5:
            continue

        by_role = [[] for _ in ROLES]
        for player, r, rank, item in assignments:
            if item[2] == 0:
                by_role[r].append(dict(id=player['id'], name=player['name'], role=ROLES[r], rank=rank))
        for group in by_role:
            rng.shuffle(group)
        matches = []
        for game in range(games):
            slots = []
            for team_index, team in enumerate(('red', 'blue')):
                if game * 2 + team_index >= teams_count: break
                for r in range(5):
                    slots.append(dict(by_role[r][game * 2 + team_index], team=team))
            matches.append(slots)
        return matches
    return []


def mutate(mode, revision, action, payload=None, path=None, actor=None):
    read_state(mode, path)
    with closing(sqlite3.connect(path or DB_PATH, timeout=10)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        state = json.loads(db.execute('SELECT body FROM activity WHERE mode=?', (mode,)).fetchone()[0])
        if revision != state['revision']:
            raise ValueError('数据已更新，请刷新后操作；本次未重复执行')
        payload = payload or {}
        if state.get('batch') and action not in ('lock-all', 'discard-all') and not action.startswith('tournament-'):
            raise ValueError('请先确认或作废本轮批量抽签')
        if action.startswith('tournament-'):
            mutate_tournament(state, action, payload, actor, mode, match_round)
        elif action == 'save':
            if state.get('tournament', {}).get('generated'):
                raise ValueError('赛事队伍已固定，不能再修改参赛人员配置')
            if state['draft']:
                raise ValueError('请先锁定或作废当前待确认场次')
            players = payload['players']
            if {p['id'] for p in players} != {p['id'] for p in state['players']} or len(players) != len(state['players']):
                raise ValueError('人员 ID 不完整或重复')
            for p in players:
                if not p['name'].strip() or len(p['name'].strip()) > 30 or len(set(p['roles'])) != len(p['roles']) or any(r not in ROLES for r in p['roles']):
                    raise ValueError('姓名或位置配置无效')
                p['name'] = p['name'].strip()
            state['players'] = players
        elif action == 'draw':
            if state['draft']:
                raise ValueError('已有待确认场次，请先处理')
            seed = uuid4().hex
            pool = copy.deepcopy(eligible(state))
            previous = {p['id'] for m in state['history'] if m['status'] == 'locked' and m['round'] == state['round'] - 1 for p in m['slots']}
            for p in pool:
                p['round_penalty'] = 100 if p['id'] in previous else 0
            slots = match(pool, seed)
            state['draft'] = dict(id=uuid4().hex, round=state['round'], seed=seed, rule='positions-v1', status='draft', slots=slots,
                                  snapshot=copy.deepcopy(pool), created_by=actor, created_at=datetime.now(timezone.utc).isoformat())
        elif action == 'draw-all':
            seed = uuid4().hex
            batch_id = uuid4().hex
            existing = state['draft']
            occupied = {p['id'] for p in existing['slots']} if existing else set()
            pool = copy.deepcopy([p for p in eligible(state) if p['id'] not in occupied])
            previous = {p['id'] for m in state['history'] if m['status'] == 'locked' and m['round'] == state['round'] - 1 for p in m['slots']}
            for p in pool:
                p['round_penalty'] = 1000 if p['id'] in previous else 0
            groups = match_round(pool, seed)
            if not groups and not existing:
                # Reuse the detailed infeasibility explanation from single draw.
                match(pool, seed)
                raise ValueError('无法组成完整两队')
            matches = [existing] if existing else []
            for slots in groups:
                matches.append(dict(id=uuid4().hex, round=state['round'], seed=seed,
                                    rule='round-flow-v1', status='draft', slots=slots,
                                    created_by=actor, created_at=datetime.now(timezone.utc).isoformat()))
            for item in matches:
                item['batch_id'] = batch_id
            state['batch'] = dict(id=batch_id, seed=seed, snapshot=pool, matches=matches)
            state['draft'] = None
        elif action in ('lock-all', 'discard-all'):
            batch = state.get('batch')
            if not batch or batch['id'] != payload.get('id'):
                raise ValueError('批量抽签已变化，请刷新')
            reason = payload.get('reason', '').strip()
            if action == 'discard-all' and not reason:
                raise ValueError('请填写作废原因')
            for item in batch['matches']:
                item.update(status='locked' if action == 'lock-all' else 'discarded', reason=reason,
                            completed_by=actor, completed_at=datetime.now(timezone.utc).isoformat())
                # Preserve the shared candidate snapshot after batch finalization.
                item.setdefault('snapshot', batch['snapshot'])
                state['history'].append(item)
            state['batch'] = None
        elif action in ('lock', 'discard'):
            draft = state['draft']
            if not draft or draft['id'] != payload.get('id'):
                raise ValueError('待确认场次已变化，请刷新')
            draft['status'] = 'locked' if action == 'lock' else 'discarded'
            draft['completed_by'] = actor
            draft['completed_at'] = datetime.now(timezone.utc).isoformat()
            draft['reason'] = payload.get('reason', '').strip()
            if action == 'discard' and not draft['reason']:
                raise ValueError('请填写作废原因')
            state['history'].append(draft)
            state['draft'] = None
        elif action == 'replace':
            draft = state['draft']
            if not draft or draft['id'] != payload.get('id'):
                raise ValueError('待确认场次已变化，请刷新')
            slot = payload.get('slot', -1)
            if not isinstance(slot, int) or not 0 <= slot < 10:
                raise ValueError('无效位置')
            old = draft['slots'][slot]
            occupied = {p['id'] for p in draft['slots']}
            candidates = [p for p in eligible(state) if p['id'] not in occupied and (not p['roles'] or old['role'] in p['roles'] or p['fill'])]
            if not candidates:
                raise ValueError('没有可替换的同位置人员，请先作废并调整配置')
            seed = uuid4().hex
            rng = random.Random(seed)
            rng.shuffle(candidates)
            p = min(candidates, key=lambda p: p['roles'].index(old['role']) if old['role'] in p['roles'] else (11 if not p['roles'] else 10))
            new = dict(id=p['id'], name=p['name'], role=old['role'], team=old['team'], rank=p['roles'].index(old['role']) if old['role'] in p['roles'] else (11 if not p['roles'] else 10))
            draft.setdefault('replacements', []).append(dict(old=old, new=new, seed=seed))
            draft['slots'][slot] = new
            # Treat the replaced person as absent for the rest of this round.
            next(p for p in state['players'] if p['id'] == old['id'])['present'] = False
        elif action == 'next-round':
            if state['draft']:
                raise ValueError('请先处理待确认场次')
            state['round'] += 1
        else:
            raise ValueError('未知操作')
        remember_draw(state, state.get('tournament'))
        state['revision'] += 1
        if not state.get('tournament'):
            state['tournament'] = bracket(team_count=state.get('tournament_settings', {}).get('team_count', 18))
        for i, team in enumerate(state['tournament']['teams']):
            team.setdefault('name', chr(65 + i))
        state.setdefault('audit', []).append(dict(action=action, revision=state['revision'], actor=actor,
                                                  at=datetime.now(timezone.utc).isoformat(), match_id=payload.get('id')))
        db.execute('UPDATE activity SET body=? WHERE mode=?', (json.dumps(state, ensure_ascii=False), mode))
        return state



def public_state(token, path=None):
    """Explicit allowlist: never publish administrative state or demo data."""
    state = read_state('real', path)
    settings = state.get('public_view', {})
    tournament = state.get('tournament', {})
    if (not settings.get('enabled') or not settings.get('token') or
            not secrets.compare_digest(settings['token'], token) or
            (not tournament.get('generated') and not settings.get('draw_enabled')) or tournament.get('simulated_roster') or tournament.get('simulated_results')):
        raise ValueError('赛事尚未公开或链接已失效')
    teams = []
    for team in tournament['teams']:
        players = [dict(id=str(i), name=p['name'], role=p['role']) for i, p in enumerate(team['players'])] if settings.get('show_names') else []
        teams.append(dict(id=team['id'], name=team['name'], players=players, drawn=bool(team['players'])))
    matches = [{key: copy.deepcopy(m[key]) for key in
                ('id', 'stage', 'number', 'sources', 'best_of', 'score_a', 'score_b', 'winner', 'bans')} for m in tournament['matches']]
    updated = max([settings.get('updated_at', '')] + [m.get('updated_at', '') for m in tournament['matches']])
    return dict(updated_at=updated, show_names=bool(settings.get('show_names')), draw_enabled=bool(settings.get('draw_enabled')), revision=state['revision'], tournament=dict(
        format=tournament['format'], generated=bool(tournament.get('generated')), teams=teams, matches=matches,
        challenge_slot=tournament.get('challenge_slot'), qualification_slots=tournament.get('qualification_slots', []), playin_opponent=tournament.get('playin_opponent'), rules_version=tournament.get('rules_version'), bye_team_id=tournament.get('bye_team_id'), last_draw_team_ids=tournament.get('last_draw_team_ids', []), team_count=len(tournament['teams']), draw_total=len(tournament['teams']) if tournament.get('draw_unit')=='team' else 10 if len(tournament['teams']) == 19 else 9, draw_unit=tournament.get('draw_unit','match'), draw_round=tournament.get('draw_round',1), drawn_teams=sum(bool(team['players']) for team in tournament['teams']), drawn_matches=tournament.get('drawn_matches', (10 if len(tournament['teams']) == 19 else 9) if tournament.get('generated') else 0), reserves=[]))
