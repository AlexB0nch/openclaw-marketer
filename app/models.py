"""SQLAlchemy ORM models."""

from sqlalchemy import BigInteger, Boolean, Column, Date, ForeignKey, Numeric, Text, func
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id = Column(BigInteger, primary_key=True)
    name = Column(Text, nullable=False)
    description = Column(Text)
    url = Column(Text)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(server_default=func.now())
    updated_at = Column(server_default=func.now())

    campaigns = relationship("Campaign", back_populates="product")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(BigInteger, primary_key=True)
    product_id = Column(BigInteger, ForeignKey("products.id", ondelete="CASCADE"))
    name = Column(Text, nullable=False)
    platform = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="draft")
    budget_rub = Column(Numeric(12, 2))
    starts_at = Column()
    ends_at = Column()
    created_at = Column(server_default=func.now())
    updated_at = Column(server_default=func.now())

    product = relationship("Product", back_populates="campaigns")
    metrics = relationship("Metrics", back_populates="campaign")


class Metrics(Base):
    __tablename__ = "metrics"

    id = Column(BigInteger, primary_key=True)
    campaign_id = Column(BigInteger, ForeignKey("campaigns.id", ondelete="CASCADE"))
    date = Column(Date, nullable=False)
    impressions = Column(BigInteger, nullable=False, default=0)
    clicks = Column(BigInteger, nullable=False, default=0)
    spend_rub = Column(Numeric(12, 2), nullable=False, default=0)
    conversions = Column(BigInteger, nullable=False, default=0)

    campaign = relationship("Campaign", back_populates="metrics")
