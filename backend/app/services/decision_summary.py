"""Bounded model jobs, keyed by the exact evidence and warehouse scope."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
import json
from threading import BoundedSemaphore, Lock
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
from app.db.session import SessionLocal
from app.services.model_client import chat_completion

_lock = Lock()
_evidence = OrderedDict()
_jobs = OrderedDict()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='decision-summary')
_slots = BoundedSemaphore(4)
TTL = 600
MAX_ITEMS = 64


def _prune(cache):
    for key in list(cache):
        if cache[key]['expires'] <= monotonic():
            del cache[key]
    while len(cache) > MAX_ITEMS:
        cache.popitem(last=False)


def remember(evidence):
    version = sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    with _lock:
        _evidence[version] = {'expires': monotonic() + TTL, 'data': deepcopy(evidence)}
        _evidence.move_to_end(version)
        _prune(_evidence)
    return version


def _state(job):
    return {key: job[key] for key in ('ai_status', 'ai_summary')}


def _run(key, token, evidence):
    try:
        # Never share a request's database session with the worker thread.
        with SessionLocal() as db:
            summary = chat_completion(db, [
                {'role': 'system', 'content': SUMMARY_PROMPT},
                {'role': 'user', 'content': json.dumps(evidence, ensure_ascii=False)},
            ], max_tokens=4096)
        state = {'ai_status': 'ready', 'ai_summary': summary} if summary.strip() else {
            'ai_status': 'unavailable', 'ai_summary': '模型未返回建议，业务指标及规则决策仍可使用。'}
    except Exception:
        # Provider errors may contain credentials or echoed request payloads.
        state = {'ai_status': 'unavailable', 'ai_summary': '模型暂不可用，业务指标及规则决策仍可使用，请稍后重新生成。'}
    finally:
        _slots.release()
    with _lock:
        if key in _jobs and _jobs[key]['token'] == token:
            _jobs[key].update(state, expires=monotonic() + TTL)


def summary_state(version, warehouses, *, start=False, refresh=False):
    with _lock:
        _prune(_evidence)
        _prune(_jobs)
        source = _evidence.get(version)
        if source is None or tuple(source['data']['warehouses']) != warehouses:
            raise HTTPException(409, '分析数据已过期或仓库范围不匹配，请重新查询')
        job = _jobs.get(version)
        if job and (job['ai_status'] == 'pending' or not refresh):
            return _state(job)
        if not start:
            return {'ai_status': 'idle', 'ai_summary': ''}
        if not _slots.acquire(blocking=False):
            return {'ai_status': 'busy', 'ai_summary': '分析任务繁忙，业务数据已可查看，请稍后重新生成。'}
        token = uuid4().hex
        job = {'ai_status': 'pending', 'ai_summary': '', 'token': token, 'expires': monotonic() + TTL}
        _jobs[version] = job
        _jobs.move_to_end(version)
        _prune(_jobs)
        try:
            _executor.submit(_run, version, token, deepcopy(source['data']))
        except Exception:
            _slots.release()
            del _jobs[version]
            raise
        return _state(job)


SUMMARY_PROMPT = """
你是销售与库存运营策略助手。只能依据用户提供的 JSON 数据判断，不得编造不存在的销售额、订单数、库存、渠道或商品信息。

请输出一份清晰、有条理的经营建议，格式固定为：
一、总体判断：先给结论，再说明影响。要直接指出当前最重要的问题、机会或风险。
二、销售侧：围绕近30天销售额、订单数、销量、客单价、环比变化、TOP渠道表现给出判断。说明哪些渠道值得继续投入，哪些渠道需要复核或调整。
三、库存侧：围绕缺货、负库存、可用库存为零、90天无销量、超储、临期/过期给出判断。说明库存是否能支撑当前销售，以及哪些问题需要优先处理。
四、销售库存联动动作：把销售表现和库存动作连起来，给出可执行建议，例如补货、停止补货、调拨、清货、渠道投放、数据复核。

要求：
- 用中文。
- 四节都要完整输出，全文约800至1200字，每节优先2至3项关键判断与动作；不要逐项重复JSON中的全部记录。
- 每一段先说结论，再说原因或动作。
- 分点输出，每点尽量只表达一个判断，避免长句堆叠。
- 不要使用 Markdown 表格。
- 不要泛泛而谈；建议尽量带上具体指标、渠道、仓库或商品问题。
- 数据不足时，明确说明缺少什么，不要猜测。
- 销售数据为全部销售；仓库筛选只作用于库存，不得把全部销售表述为所选仓库销售。
""".strip()
