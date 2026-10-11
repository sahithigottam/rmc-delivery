"""Country, state, and city reference tables."""
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, String, func, text
from sqlalchemy.orm import relationship

from app.db.database import Base
from app.db.types import UTCDateTime

__all__ = ["Country", "BusinessCountry", "State", "City"]


class Country(Base):
    """ISO 3166-1 country reference keyed by its alpha-2 code."""

    __tablename__ = "countries"
    __table_args__ = (
        CheckConstraint(
            "length(code) = 2 AND code = upper(code) "
            "AND substr(code, 1, 1) BETWEEN 'A' AND 'Z' "
            "AND substr(code, 2, 1) BETWEEN 'A' AND 'Z'",
            name="country_code_format",
        ),
        CheckConstraint("length(trim(name)) > 0", name="country_name_not_empty"),
    )

    code = Column(String(2), primary_key=True)
    name = Column(String(200), nullable=False)
    created_at = Column(UTCDateTime(), nullable=False, server_default=func.now())
    updated_at = Column(
        UTCDateTime(), nullable=False, server_default=func.now(), onupdate=func.now(),
    )


class State(Base):
    """Administrative area within a country."""

    __tablename__ = "states"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="state_name_not_empty"),
        Index("uq_states_owner_country_name_ci", "organization_id", "country_code", text("lower(name)"), unique=True),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id = Column(String(100), ForeignKey("businesses.id"), nullable=True, index=True)
    country_code = Column(
        String(2), ForeignKey("countries.code", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    name = Column(String(200), nullable=False)
    created_at = Column(UTCDateTime(), nullable=False, server_default=func.now())
    updated_at = Column(
        UTCDateTime(), nullable=False, server_default=func.now(), onupdate=func.now(),
    )


class City(Base):
    """City or locality within a state, with its authoritative IANA timezone."""

    __tablename__ = "cities"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="city_name_not_empty"),
        CheckConstraint("length(trim(timezone)) > 0", name="city_timezone_not_empty"),
        Index("uq_cities_state_name_ci", "state_id", text("lower(name)"), unique=True),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id = Column(String(100), ForeignKey("businesses.id"), nullable=True, index=True)
    state_id = Column(
        String(36), ForeignKey("states.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    name = Column(String(200), nullable=False)
    timezone = Column(String(100), nullable=False)
    state = relationship("State", lazy="joined")
    created_at = Column(UTCDateTime(), nullable=False, server_default=func.now())
    updated_at = Column(
        UTCDateTime(), nullable=False, server_default=func.now(), onupdate=func.now(),
    )


class BusinessCountry(Base):
    """Private country entry; global Country codes remain internal FK anchors."""

    __tablename__ = "business_countries"
    organization_id = Column(String(100), ForeignKey("businesses.id"), primary_key=True)
    code = Column(String(2), ForeignKey("countries.code"), primary_key=True)
    name = Column(String(200), nullable=False)
    created_at = Column(UTCDateTime(), nullable=False, server_default=func.now())
