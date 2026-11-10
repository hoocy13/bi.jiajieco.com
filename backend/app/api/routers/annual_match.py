from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_user, require_permission
from app.models.user import User
from app.schemas.common import ok
from app.services import annual_match as service

router = APIRouter(prefix='/annual-match', tags=['annual-match'], dependencies=[Depends(require_permission('system.users.manage'))])
Mode = Literal['real', 'demo']


class Player(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=30)
    present: bool
    roles: list[str] = Field(max_length=5)
    fill: bool


class BanGame(BaseModel):
    game: int = Field(ge=1, le=5)
    red: list[str] = Field(default_factory=list, max_length=10)
    blue: list[str] = Field(default_factory=list, max_length=10)


class Command(BaseModel):
    revision: int = Field(ge=0)
    players: list[Player] | None = Field(default=None, max_length=200)
    id: str | None = None
    team_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=20)
    slot: int | None = None
    reason: str = Field(default='', max_length=200)
    score_a: int | None = Field(default=None, ge=0, le=3)
    score_b: int | None = Field(default=None, ge=0, le=3)
    bans: list[BanGame] | None = Field(default=None, max_length=5)
    simulation: bool = False
    enabled: bool = False
    show_names: bool = False
    draw_enabled: bool = False


@router.get('/{mode}')
def get_state(mode: Mode):
    return ok(service.read_state(mode))


@router.post('/{mode}/{action}')
def command(mode: Mode, action: Literal['save', 'draw', 'draw-all', 'lock', 'lock-all', 'discard', 'discard-all', 'replace', 'next-round', 'tournament-generate', 'tournament-score', 'tournament-demo', 'tournament-challenge', 'tournament-upgrade', 'tournament-public', 'tournament-restore', 'tournament-abandon', 'tournament-rename'], body: Command, user: User = Depends(get_current_user)):
    if action == 'save' and body.players is None:
        raise HTTPException(422, '缺少人员配置')
    try:
        return ok(service.mutate(mode, body.revision, action, body.model_dump(exclude_none=True), actor=user.id))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


public_router = APIRouter(prefix='/public/annual-events', tags=['public-annual-events'])


@public_router.get('/{token}')
def get_public_event(token: str):
    from fastapi.responses import JSONResponse
    if len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
        raise HTTPException(404, '赛事尚未公开或链接已失效')
    try:
        return JSONResponse(content=ok(service.public_state(token)), headers={'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex, nofollow'})
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@public_router.post('/{token}/draw', dependencies=[Depends(require_permission('system.users.manage'))])
def public_draw(token: str, body: Command, user: User = Depends(get_current_user)):
    try:
        service.mutate('real', body.revision, 'tournament-public-draw', {'token': token}, actor=user.id)
        return ok(service.public_state(token))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
