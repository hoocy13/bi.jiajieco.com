from datetime import date

from fastapi import APIRouter, Depends, Query, File, UploadFile
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.db.session import get_db
from app.db.ods import get_ods_db
from app.models.group_buy_inbound import InboundAudit
from app.schemas.common import ok
from app.schemas.group_buy_inbound import CounterMapping, InboundAction, InboundScope, ReceiptConfirmation, ReceiptHoldAction, OrderCollectionEdit
from app.services import group_buy_inbound as service

router = APIRouter(prefix='/group-buy/inbound', tags=['group-buy-inbound'], dependencies=[Depends(require_permission('group_buy.manage'))])
manage = require_permission('group_buy.manage')


@router.get('/receipts')
def receipts(start_date: date, end_date: date, brand: str,
             state: str = Query('pending', pattern='^(all|pending|partial|waiting|done|excluded)$'),
             keyword: str = Query('', max_length=128), supplier: str = Query('', max_length=255),
             supplier_names: list[str] | None = Query(None, max_length=100),
             product_keys: list[str] | None = Query(None, max_length=100),
             page: int = Query(1, ge=1), page_size: int = Query(30, ge=10, le=100),
             sort_by: str = Query('receipt_time', pattern='^(receipt_time|receipt_number|item_count|pending_count)$'),
             sort_order: str = Query('desc', pattern='^(asc|desc)$'), db: Session = Depends(get_db)):
    return ok(service.list_receipts(db, start_date, end_date, brand, state, keyword, supplier,
        page, page_size, sort_by, sort_order, supplier_names, product_keys))


@router.get('/receipts/{doc_id}')
def receipt(doc_id: str, brand: str, batch_id: int | None = Query(None, gt=0), db: Session = Depends(get_db)):
    return ok(service.receipt_detail(db, doc_id, brand, batch_id))


@router.post('/receipts/{doc_id}/hold')
def hold_receipt(doc_id: str, brand: str, body: ReceiptHoldAction, db: Session = Depends(get_db), user=Depends(manage)):
    try:
        return ok(service.set_receipt_hold(db, doc_id, brand, body, user.username))
    except IntegrityError:
        db.rollback();service.fail('待补状态已更新，请刷新',409)


@router.get('/order-collections')
def order_collections(month: str = Query(...,pattern=r'^\d{4}-(0[1-9]|1[0-2])$'), brand: str = '', db: Session = Depends(get_db)):
    return ok(service.list_order_collections(db,month,brand))


@router.post('/order-collections')
def update_order_collection(body: OrderCollectionEdit, db: Session = Depends(get_db), user=Depends(manage)):
    try:
        return ok(service.save_order_collection(db,body,user.username))
    except IntegrityError:
        db.rollback();service.fail('收集状态已更新，请刷新',409)


@router.post('/receipt-confirmations')
def confirm_receipt(body: ReceiptConfirmation, db: Session = Depends(get_db), user=Depends(manage)):
    return ok(service.confirm_receipt(db, body, user.username))


@router.get('/options')
def options(db: Session = Depends(get_db)):
    return ok(service.options(db))


@router.post('/sync')
def sync(body: InboundScope, db: Session = Depends(get_db), ods: Session = Depends(get_ods_db), user=Depends(manage)):
    try:
        return ok(service.sync_source(db, ods, body, user.username))
    except IntegrityError:
        db.rollback()
        service.fail('其他人正在同步，请刷新后重试', 409)
    except SQLAlchemyError:
        db.rollback()
        service.fail('采集数据读取或同步失败，上次结果已保留，请稍后重试', 503)


@router.post('/suppliers/import')
async def import_suppliers(file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(manage)):
    return ok(service.import_suppliers(db, await file.read(5*1024*1024+1), user.username))


@router.get('/lines')
def lines(start_date: date, end_date: date, brand: str, batch_id: int | None = None,
          state: str = Query('pending', pattern='^(all|pending|ready|confirmed|excluded)$'),
          keyword: str = Query('', max_length=128), supplier: str = Query('', max_length=255),
          supplier_names: list[str] | None = Query(None, max_length=100),
          product_keys: list[str] | None = Query(None, max_length=100),
          page: int = Query(1, ge=1), page_size: int = Query(30, ge=10, le=100),
          sort_by: str = Query('receipt_time', pattern='^(receipt_time|receipt_number|barcode|quantity)$'),
          sort_order: str = Query('desc', pattern='^(asc|desc)$'), db: Session = Depends(get_db)):
    return ok(service.list_lines(db, start_date, end_date, brand, batch_id, state, keyword, supplier, page, page_size, sort_by, sort_order,
                                 supplier_names=supplier_names, product_keys=product_keys))


@router.post('/mapping')
def mapping(body: CounterMapping, db: Session = Depends(get_db), user=Depends(manage)):
    try:
        service.save_mapping(db, body, user.username)
    except IntegrityError:
        db.rollback()
        service.fail('柜台对应已更新，请刷新后重试', 409)
    return ok()


@router.post('/actions')
def actions(body: InboundAction, db: Session = Depends(get_db), user=Depends(manage)):
    return ok(service.act(db, body, user.username))


@router.get('/progress/{batch_id}')
def progress(batch_id: int, product_id: str = '', source_id: str = '', db: Session = Depends(get_db)):
    return ok(service.progress(db, batch_id, product_id, source_id))


@router.get('/history/{line_id}')
def history(line_id: int, db: Session = Depends(get_db)):
    rows = db.query(InboundAudit).filter(InboundAudit.line_id == line_id).order_by(InboundAudit.id.desc()).limit(100).all()
    return ok([{'id': r.id, 'action': r.action, 'operator': r.operator, 'created_at': r.created_at.isoformat(),
        'changes': r.changes} for r in rows])


@router.get('/comparison/{line_id}')
def comparison(line_id: int, batch_id: int | None = Query(None, gt=0), source_id: str = '', db: Session = Depends(get_db)):
    return ok(service.comparison(db, line_id, batch_id, source_id))
