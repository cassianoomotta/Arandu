import enum
from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    String, 
    Text, 
    Boolean, 
    DateTime, 
    ForeignKey, 
    Index, 
    Enum as SQLEnum, 
    func,
    JSON,
    Float,
    Integer
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Base class for SQLAlchemy 2.0 declarative models
class Base(DeclarativeBase):
    pass

# Custom Python Enums that map to PostgreSQL Enum types
class SourceType(str, enum.Enum):
    NACIONAL = "Nacional"
    INTERNACIONAL = "Internacional"

class SendStatus(str, enum.Enum):
    PENDENTE = "pendente"
    ENVIADO_TELEGRAM = "enviado_telegram"
    FALHA = "falha"

class UserRole(str, enum.Enum):
    ADMIN = "Admin"
    LEITOR = "Leitor"


class Source(Base):
    """
    Represents the RSS feeds and content sources.
    """
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rss_url: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    type: Mapped[SourceType] = mapped_column(
        SQLEnum(SourceType, name="source_type_enum"), 
        nullable=False, 
        default=SourceType.NACIONAL
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Metadata audit columns
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        server_default=func.now(), 
        onupdate=func.now()
    )

    # Relationship: One source can have many news items
    news: Mapped[List["News"]] = relationship(
        "News", 
        back_populates="source", 
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Source(id={self.id}, name='{self.name}', type='{self.type.value}', active={self.active})>"


class News(Base):
    """
    Represents a curated news article.
    Includes fields for deduplication, translation, and AI summary.
    """
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), 
        nullable=False
    )
    original_title: Mapped[str] = mapped_column(String(255), nullable=False)
    translated_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    link: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # og:image
    original_published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Deduplication fields
    hash_title: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    
    # For semantic similarity deduplication
    # We can store key phrases / reduced key (chave_reduzida) as Text
    reduced_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Flag to track if the title was translated using Gemini
    translated_by_gemini: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=False)
    
    # We can also store the similarity vector (vetor_similaridade) as an Array of Floats.
    # Note: If pgvector is installed in Postgres, you could use Vector(dimensions) from pgvector.sqlalchemy.
    # Here we use JSON to remain cross-platform out-of-the-box (compatible with SQLite and PostgreSQL).
    similarity_vector: Mapped[Optional[List[float]]] = mapped_column(
        JSON, 
        nullable=True
    )
    
    # Delivery status
    send_status: Mapped[SendStatus] = mapped_column(
        SQLEnum(SendStatus, name="send_status_enum"), 
        nullable=False, 
        default=SendStatus.PENDENTE
    )

    # AI Classification and Curation fields
    relevance_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ai_justification: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    priority: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_curated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    curated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    destaque: Mapped[Optional[bool]] = mapped_column(Boolean, default=False, nullable=True)

    # Editorial Executivo fields
    editorial_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default="pendente")
    editorial_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    editorial_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    editorial_category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    editorial_tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    editorial_scores: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Metadata audit columns
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        server_default=func.now(), 
        onupdate=func.now()
    )

    # Relationship: News belongs to a source
    source: Mapped["Source"] = relationship("Source", back_populates="news")

    def __repr__(self) -> str:
        return f"<News(id={self.id}, original_title='{self.original_title[:30]}...', status='{self.send_status.value}', editorial_status='{self.editorial_status}')>"

# Explicitly defining indexes on the news table for optimal performance
Index("ix_news_hash_title", News.hash_title, unique=True)
Index("ix_news_send_status", News.send_status)
Index("ix_news_source_id", News.source_id)
Index("ix_news_original_published_at_desc", News.original_published_at.desc())
Index("ix_news_is_curated", News.is_curated)
Index("ix_news_relevance_score", News.relevance_score)
Index("ix_news_editorial_status", News.editorial_status)
Index("ix_news_editorial_pubdate", News.editorial_status, News.original_published_at.desc())
Index("ix_news_category_pubdate", News.editorial_category, News.original_published_at.desc())
Index("ix_news_curated_pubdate", News.is_curated, News.original_published_at.desc())


class User(Base):
    """
    Represents users of the curating portal.
    """
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole, name="user_role_enum"), 
        nullable=False, 
        default=UserRole.LEITOR
    )

    # Metadata audit columns
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        server_default=func.now(), 
        onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}', role='{self.role.value}')>"

# Index on email for fast authentication lookups
Index("ix_users_email", User.email, unique=True)


class Lead(Base):
    """
    Represents lead/customer capture data from the landing page.
    """
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    whatsapp: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<Lead(id={self.id}, name='{self.name}', email='{self.email}')>"

# Index on email for fast lead lookups
Index("ix_leads_email", Lead.email, unique=True)


class PipelineStatus(Base):
    """
    Tracks the real-time execution status of the background scraper/AI pipeline.
    """
    __tablename__ = "pipeline_status"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="idle")  # idle, running, failed
    current_phase: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    current_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        server_default=func.now(), 
        onupdate=func.now()
    )


class ActiveSession(Base):
    """
    Tracks active logged in user sessions to enforce concurrency limits.
    """
    __tablename__ = "active_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    def __repr__(self) -> str:
        return f"<ActiveSession(id={self.id}, user_id={self.user_id}, expires_at={self.expires_at})>"

Index("ix_active_sessions_token", ActiveSession.token, unique=True)


class NoticiasRejeitadas(Base):
    """
    Represents rejected news articles, storing the reason and metadata.
    """
    __tablename__ = "noticias_rejeitadas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    id_noticia: Mapped[int] = mapped_column(Integer, nullable=False)
    titulo: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    link: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    motivo_rejeicao: Mapped[str] = mapped_column(Text, nullable=False)
    data_rejeicao: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    categoria_identificada: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    def __repr__(self) -> str:
        return f"<NoticiasRejeitadas(id={self.id}, id_noticia={self.id_noticia}, motivo_rejeicao='{self.motivo_rejeicao[:30]}...')>"




