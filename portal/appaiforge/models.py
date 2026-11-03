"""Modelo de dados do portal (ADR 0007; change appai-forge-mvp task 1.3)."""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class UserType(str, enum.Enum):
    admin = "admin"
    editor = "editor"
    app_user = "app_user"


class SystemStatus(str, enum.Enum):
    provisioning = "provisioning"
    active = "active"
    error = "error"
    archived = "archived"


class RunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    awaiting_approval = "awaiting_approval"
    succeeded = "succeeded"
    interrupted = "interrupted"
    failed = "failed"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    type: Mapped[UserType] = mapped_column(Enum(UserType, name="user_type"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def is_admin(self) -> bool:
        return self.type == UserType.admin

    @property
    def is_editor(self) -> bool:
        return self.type == UserType.editor


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)


class System(Base):
    __tablename__ = "systems"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="glm")
    model: Mapped[str] = mapped_column(String(120), default="glm-4.6")
    status: Mapped[SystemStatus] = mapped_column(Enum(SystemStatus, name="system_status"), default=SystemStatus.provisioning)
    status_message: Mapped[str] = mapped_column(Text, default="")
    container_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    identity_secret: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SystemGroup(Base):
    __tablename__ = "system_groups"

    system_id: Mapped[str] = mapped_column(ForeignKey("systems.id"), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), primary_key=True)


class DbConnection(Base):
    __tablename__ = "db_connections"
    __table_args__ = (UniqueConstraint("system_id", "name", name="uq_connection_per_system"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    system_id: Mapped[str] = mapped_column(ForeignKey("systems.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default="postgres")
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=5432)
    database: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(255))
    password_encrypted: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    system_id: Mapped[str] = mapped_column(ForeignKey("systems.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    harness_session_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    system_id: Mapped[str] = mapped_column(ForeignKey("systems.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    user_email: Mapped[str] = mapped_column(String(255), default="")
    chat_session_id: Mapped[str | None] = mapped_column(ForeignKey("chat_sessions.id"), nullable=True)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus, name="run_status"), default=RunStatus.queued)
    prompt: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    system_id: Mapped[str] = mapped_column(ForeignKey("systems.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    git_sha: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    author_email: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TokenUsage(Base):
    __tablename__ = "token_usage"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    system_id: Mapped[str] = mapped_column(ForeignKey("systems.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    user_email: Mapped[str] = mapped_column(String(255), default="")
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Guideline(Base):
    __tablename__ = "guidelines"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text)
    updated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by_email: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderKey(Base):
    __tablename__ = "provider_keys"

    provider: Mapped[str] = mapped_column(String(40), primary_key=True)
    key_encrypted: Mapped[str] = mapped_column(String(500))


class LlmProvider(Base):
    """Catálogo de provedores de LLM (capability llm-provider-catalog)."""

    __tablename__ = "llm_provider"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30), default="openai-compatible")  # native | openai-compatible
    provider_id: Mapped[str] = mapped_column(String(60))
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    env_name: Mapped[str] = mapped_column(String(60), default="")
    models: Mapped[list] = mapped_column(JSON, default=list)
    is_preset: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GateDecision(Base):
    __tablename__ = "gate_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    system_id: Mapped[str] = mapped_column(ForeignKey("systems.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True, index=True)
    origin: Mapped[str] = mapped_column(String(10))  # agente | app
    sql: Mapped[str] = mapped_column(Text)
    connection_name: Mapped[str] = mapped_column(String(120), default="")
    classification: Mapped[str] = mapped_column(String(12))  # normal | confirmavel | bloqueada
    decision: Mapped[str] = mapped_column(String(10))  # aprovada | recusada | bloqueada
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    author_email: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class RunEventRecord(Base):
    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ManagementAudit(Base):
    """Trilha de auditoria das ações de escrita da gestão (capability management-audit)."""

    __tablename__ = "management_audit"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor_email: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(60), index=True)
    resource_type: Mapped[str] = mapped_column(String(40), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    system_id: Mapped[str | None] = mapped_column(ForeignKey("systems.id"), nullable=True, index=True)
    details: Mapped[dict] = mapped_column(JSON, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
