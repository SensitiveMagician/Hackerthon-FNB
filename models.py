from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, BigInteger, String, Text, func
from .database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(160), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    phone = Column(String(40), nullable=False)
    role = Column(String(40), nullable=False)
    password_hash = Column(String(255), nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)
    verification_token_hash = Column(String(64), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Profile(Base):
    __tablename__ = "profiles"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    data_json = Column(Text, default="{}", nullable=False)
    completed = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class BusinessPlan(Base):
    __tablename__ = "business_plans"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    plan_json = Column(Text, nullable=False)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())


class TransactionRecord(Base):
    __tablename__ = "transaction_records"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    transaction_date = Column(String(10), nullable=False)
    transaction_type = Column(String(20), nullable=False)
    description = Column(String(240), nullable=False)
    category = Column(String(60), default="Other", nullable=False)
    amount = Column(BigInteger, nullable=False)  # amount stored in cents to avoid floating-point rounding
    quantity = Column(String(40), default="1", nullable=False)
    payment_method = Column(String(40), default="Other", nullable=False)
    source = Column(String(20), default="typed", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TransactionAudit(Base):
    __tablename__ = "transaction_audits"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    transaction_id = Column(Integer, index=True, nullable=True)
    action = Column(String(20), nullable=False)  # created, updated, deleted, duplicate_blocked
    raw_input = Column(Text, nullable=True)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SupplierListing(Base):
    __tablename__ = "supplier_listings"
    id = Column(Integer, primary_key=True, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    supplier_name = Column(String(180), nullable=False)
    category = Column(String(100), nullable=False)
    description = Column(Text, default="", nullable=False)
    price = Column(Integer, nullable=True)  # cents, optional indicative unit price
    unit = Column(String(60), default="unit", nullable=False)
    location = Column(String(180), default="", nullable=False)
    contact_name = Column(String(180), default="", nullable=False)
    contact_email = Column(String(255), default="", nullable=False)
    contact_phone = Column(String(60), default="", nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class BusinessOrder(Base):
    __tablename__ = "business_orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    supplier_listing_id = Column(Integer, ForeignKey("supplier_listings.id", ondelete="SET NULL"), nullable=True)
    supplier_name = Column(String(180), nullable=False)
    item_or_service = Column(String(240), nullable=False)
    quantity = Column(String(40), default="1", nullable=False)
    quoted_total = Column(Integer, nullable=True)  # cents
    delivery_address = Column(String(300), default="", nullable=False)
    notes = Column(Text, default="", nullable=False)
    status = Column(String(40), default="requested", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class FounderDocument(Base):
    __tablename__ = "founder_documents"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    document_type = Column(String(100), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
