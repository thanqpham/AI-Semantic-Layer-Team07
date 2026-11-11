"""Persistence models for manually declared EAV source configurations."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.db_base import Base, utc_now

EAV_DATA_TYPE_CHECK = "data_type IN ('string', 'number', 'boolean', 'date', 'datetime')"
EAV_MULTI_VALUE_RULE_CHECK = "multi_value_rule IN ('reject', 'first', 'last', 'sum', 'avg', 'min', 'max')"
EAV_REVIEW_STATUS_CHECK = "review_status IN ('pending_review', 'approved', 'rejected')"


class EavSourceConfigModel(Base):
    """One EAV source declaration pending or approved for a semantic database."""

    __tablename__ = "eav_source_configs"
    __table_args__ = (
        UniqueConstraint("semantic_db_id", "entity_table", name="uq_eav_source_config_entity_table"),
        CheckConstraint(EAV_REVIEW_STATUS_CHECK, name="ck_eav_source_config_review_status"),
        CheckConstraint("attribute_mode IN ('direct', 'dictionary')", name="ck_eav_source_config_mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    semantic_db_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("semantic_databases.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_table: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_id_column: Mapped[str] = mapped_column(String(200), nullable=False)
    attribute_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    attribute_column: Mapped[str | None] = mapped_column(String(200), nullable=True)
    attribute_fk_column: Mapped[str | None] = mapped_column(String(200), nullable=True)
    dict_table: Mapped[str | None] = mapped_column(String(200), nullable=True)
    dict_key_column: Mapped[str | None] = mapped_column(String(200), nullable=True)
    dict_label_column: Mapped[str | None] = mapped_column(String(200), nullable=True)
    value_columns: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    history: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_review")
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    attributes: Mapped[list["EavAttributeModel"]] = relationship(
        "EavAttributeModel", back_populates="config", cascade="all, delete-orphan"
    )


class EavAttributeModel(Base):
    """One declared attribute of an EAV source configuration."""

    __tablename__ = "eav_attributes"
    __table_args__ = (
        UniqueConstraint("config_id", "attribute_key", name="uq_eav_attribute_key"),
        CheckConstraint(EAV_DATA_TYPE_CHECK, name="ck_eav_attribute_data_type"),
        CheckConstraint(EAV_MULTI_VALUE_RULE_CHECK, name="ck_eav_attribute_multi_value_rule"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("eav_source_configs.id", ondelete="CASCADE"), nullable=False
    )
    attribute_key: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data_type: Mapped[str] = mapped_column(String(20), nullable=False)
    value_column: Mapped[str | None] = mapped_column(String(200), nullable=True)
    multi_value_rule: Mapped[str] = mapped_column(String(20), nullable=False, default="reject")
    history_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    config: Mapped["EavSourceConfigModel"] = relationship("EavSourceConfigModel", back_populates="attributes")
