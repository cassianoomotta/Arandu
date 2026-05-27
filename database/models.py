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
    JSON
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
        return f"<News(id={self.id}, original_title='{self.original_title[:30]}...', status='{self.send_status.value}')>"

# Explicitly defining indexes on the news table for optimal performance
# 1. Index on hash_title for duplicate checks (SQLAlchemy automatically creates unique index for unique=True, but we explicitly note it here)
# 2. Index on send_status for polling pending news
# 3. Index on source_id for relational joins
# 4. Index on original_published_at DESC for fetching latest news fast
# 5. Index on link (automatically unique)
Index("ix_news_hash_title", News.hash_title, unique=True)
Index("ix_news_send_status", News.send_status)
Index("ix_news_source_id", News.source_id)
Index("ix_news_original_published_at_desc", News.original_published_at.desc())


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

