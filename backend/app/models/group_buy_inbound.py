from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class InboundSupplier(Base):
    __tablename__ = 'group_buy_inbound_suppliers'
    code: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(128), default='')
    alias: Mapped[str] = mapped_column(String(255), default='')
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class InboundCounter(Base):
    __tablename__ = 'group_buy_inbound_counters'
    __table_args__ = (UniqueConstraint('brand', 'name'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))


class InboundAlias(Base):
    __tablename__ = 'group_buy_inbound_aliases'
    __table_args__ = (UniqueConstraint('brand', 'supplier'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str] = mapped_column(String(32))
    supplier: Mapped[str] = mapped_column(String(255))
    counter_id: Mapped[int] = mapped_column(ForeignKey('group_buy_inbound_counters.id'))
    supplier_code: Mapped[str | None] = mapped_column(String(128), nullable=True)


class InboundBinding(Base):
    __tablename__ = 'group_buy_inbound_bindings'
    __table_args__ = (UniqueConstraint('batch_id', 'source_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey('group_buy_batches.id'), index=True)
    source_id: Mapped[str] = mapped_column(String(32))
    counter_id: Mapped[int] = mapped_column(ForeignKey('group_buy_inbound_counters.id'))


class InboundLine(Base):
    __tablename__ = 'group_buy_inbound_lines'
    __table_args__ = (UniqueConstraint('doc_id', 'rec_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(32))
    rec_id: Mapped[str] = mapped_column(String(32))
    brand: Mapped[str] = mapped_column(String(32), index=True)
    receipt_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(16), default='pending')
    batch_id: Mapped[int | None] = mapped_column(ForeignKey('group_buy_batches.id'), nullable=True, index=True)
    source_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    product_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_barcode: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str] = mapped_column(String(500), default='')
    operator: Mapped[str] = mapped_column(String(64), default='')
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class InboundAudit(Base):
    __tablename__ = 'group_buy_inbound_audits'
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey('group_buy_inbound_lines.id'), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(32))
    changes: Mapped[dict] = mapped_column(JSON)
    operator: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class InboundSubstitution(Base):
    """Explicit order credit; original warehouse receipt stays on InboundLine."""
    __tablename__ = 'group_buy_inbound_substitutions'
    line_id: Mapped[int] = mapped_column(ForeignKey('group_buy_inbound_lines.id'), primary_key=True)
    credit_quantity: Mapped[int] = mapped_column()
    source_quantity: Mapped[str] = mapped_column(String(64))


class InboundSync(Base):
    __tablename__ = 'group_buy_inbound_syncs'
    scope: Mapped[str] = mapped_column(String(128), primary_key=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    source_updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    line_count: Mapped[int] = mapped_column(default=0)


class InboundReceiptHold(Base):
    __tablename__ = 'group_buy_inbound_receipt_holds'
    doc_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    brand: Mapped[str] = mapped_column(String(32), primary_key=True)
    revision: Mapped[int] = mapped_column(default=1)
    waiting: Mapped[bool] = mapped_column(default=True)
    month: Mapped[str] = mapped_column(String(7))
    counter: Mapped[str] = mapped_column(String(128))
    note: Mapped[str] = mapped_column(String(500), default='')
    operator: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class InboundOrderCollection(Base):
    __tablename__ = 'group_buy_inbound_order_collections'
    __table_args__ = (UniqueConstraint('month', 'brand', 'counter', 'batch_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(7))
    brand: Mapped[str] = mapped_column(String(32))
    counter: Mapped[str] = mapped_column(String(128))
    batch_key: Mapped[str] = mapped_column(String(32), default='')
    status: Mapped[str] = mapped_column(String(16), default='missing')
    note: Mapped[str] = mapped_column(String(500), default='')
    revision: Mapped[int] = mapped_column(default=1)
    operator: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
