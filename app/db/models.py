from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    connector: Mapped[str | None] = mapped_column(String(50), nullable=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (Index("ix_offers_source_id", "source_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedup_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    seniority: Mapped[str | None] = mapped_column(String(50), nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(
        String(3), nullable=True, server_default="PLN"
    )
    contract_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    industry_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    hide: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CVVersion(Base):
    __tablename__ = "cv_versions"
    __table_args__ = (Index("ix_cv_versions_offer_id_profile_id", "offer_id", "profile_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    offer_id: Mapped[int] = mapped_column(Integer, ForeignKey("offers.id"), nullable=False)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profiles.id"), nullable=False)
    cv_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    cover_letter_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    tone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="drafted")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MatchScore(Base):
    __tablename__ = "match_scores"
    __table_args__ = (Index("ix_match_scores_offer_id_profile_id", "offer_id", "profile_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    offer_id: Mapped[int] = mapped_column(Integer, ForeignKey("offers.id"), nullable=False)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profiles.id"), nullable=False)
    engine: Mapped[str] = mapped_column(String(20), nullable=False)
    score_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    offer_id: Mapped[int] = mapped_column(Integer, ForeignKey("offers.id"), nullable=False)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profiles.id"), nullable=False)
    cv_version_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cv_versions.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="drafted")
    send_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SchedulerRun(Base):
    __tablename__ = "scheduler_runs"
    __table_args__ = (Index("ix_scheduler_runs_source_id_started_at", "source_id", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="running")
    fetched_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warning: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeadLetterMixin:
    """Common columns for a pipeline failure table (P3US33).

    One row per failing *resource* (a job posting, a source's ingestion, an
    offer x profile pair), not one row per occurrence: `dedup_key` is unique per
    table, and `record_failure` upserts on it -- a recurring failure updates the
    existing row (reopening it if resolved) instead of appending a sibling row.
    See docs/adr/0016-dead-letter-rows-are-mutable-per-resource-not-append-only.md.
    """

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    failure_type: Mapped[str] = mapped_column(String(30), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionFailure(DeadLetterMixin, Base):
    __tablename__ = "ingestion_failures"
    __table_args__ = (
        Index("ix_ingestion_failures_source_id_occurred_at", "source_id", "occurred_at"),
    )

    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    scheduler_run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("scheduler_runs.id"), nullable=True
    )
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ScoringFailure(DeadLetterMixin, Base):
    __tablename__ = "scoring_failures"
    __table_args__ = (Index("ix_scoring_failures_offer_id_occurred_at", "offer_id", "occurred_at"),)

    offer_id: Mapped[int] = mapped_column(Integer, ForeignKey("offers.id"), nullable=False)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profiles.id"), nullable=False)
