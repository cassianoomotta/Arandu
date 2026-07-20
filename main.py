import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import List, Optional

import jwt
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Depends, HTTPException, status, Query, Header, Response
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, text
from passlib.context import CryptContext

from database.config import settings
from database.connection import get_db_session, engine
from database.models import Base, News, Source, User, UserRole, SendStatus, Lead, PipelineStatus, ActiveSession
from core.scraper import main as run_scraper
from core.notifier import TelegramNotifier, dispatch_pending_notifications
from agent import AgentOrchestrator, EditorExecutivoOrchestrator

# Setup Logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("arandu_api")

# Initialize Scheduler
scheduler = AsyncIOScheduler()

async def execute_scheduled_ingestion():
    """
    Background job that runs the full news ingestion pipeline:
    1. Scraper: RSS fetching, translation, AI summary
    2. Curador de Notícias: 2-phase Gemini classification & scoring
    3. Editor Executivo: Full-text scraping, editorial synthesis
    4. Notification Dispatch: Telegram delivery of published articles
    """
    from core.status import update_pipeline_status
    logger.info("Background Scheduler: Starting full news curation cycle...")
    try:
        # 1. Run scraping, translation, and AI summarization
        await run_scraper()
        
        import os
        if os.getenv("ONLY_EDITOR", "false").lower() == "true":
            logger.info("Background Scheduler: ONLY_EDITOR mode is active. Skipping remaining stages.")
            return
        
        # 2. Run Curador de Notícias (Agent-based curation pipeline)
        try:
            logger.info("Background Scheduler: Running Curador de Notícias agent...")
            curator = AgentOrchestrator()
            curation_report = curator.run_curation_pipeline()
            logger.info(f"Background Scheduler: Curador finished. {curation_report}")
        except Exception as e:
            logger.error(f"Background Scheduler: Curador de Notícias failed: {str(e)}")
            update_pipeline_status(phase="Curadoria IA", error=str(e))
            raise e
        
        # 3. Run Editor Executivo (Editorial synthesis pipeline)
        try:
            logger.info("Background Scheduler: Running Editor Executivo agent...")
            editor = EditorExecutivoOrchestrator()
            editorial_report = editor.run_editorial_pipeline()
            logger.info(f"Background Scheduler: Editor Executivo finished. {editorial_report}")
        except Exception as e:
            logger.error(f"Background Scheduler: Editor Executivo failed: {str(e)}")
            update_pipeline_status(phase="Redação IA", error=str(e))
            raise e
        
        # 3.5. Divulgação no Site
        try:
            logger.info("Background Scheduler: Divulgando no Site...")
            update_pipeline_status(phase="Divulgação no Site", detail="Divulgando notícias qualificadas no portal...")
            with get_db_session() as session:
                published_count = session.query(News).filter(News.editorial_status == "publicado").count()
            update_pipeline_status(phase="Divulgação no Site", detail=f"Divulgação concluída. Total de {published_count} notícias ativas.")
        except Exception as e:
            logger.error(f"Background Scheduler: Divulgação failed: {str(e)}")
            update_pipeline_status(phase="Divulgação no Site", error=str(e))
            raise e

        # 4. Dispatch pending notifications via TelegramNotifier strategy
        try:
            notifier = TelegramNotifier()
            await dispatch_pending_notifications(notifier)
        except Exception as e:
            logger.error(f"Background Scheduler: Notificações failed: {str(e)}")
            update_pipeline_status(phase="Notificações", error=str(e))
            raise e
        
        update_pipeline_status(is_end=True)
        logger.info("Background Scheduler: Full news curation cycle completed successfully.")
    except Exception as e:
        logger.error(f"Background Scheduler: News curation cycle failed: {str(e)}")
        update_pipeline_status(error=str(e))


async def execute_scheduled_editor():
    """
    Background job that runs ONLY the Editor Executivo agent
    in between the main ingestion cycles to keep generating
    executive summaries for pending curated news.
    """
    from core.status import update_pipeline_status
    logger.info("Background Scheduler: Starting Editor Executivo scheduled run...")
    try:
        update_pipeline_status(phase="Redação IA", detail="Executando Editor Executivo em segundo plano para resumos pendentes...")
        editor = EditorExecutivoOrchestrator()
        editorial_report = await asyncio.to_thread(editor.run_editorial_pipeline)
        logger.info(f"Background Scheduler: Editor Executivo finished. {editorial_report}")
        
        # Trigger Telegram notifier for any newly published articles
        try:
            update_pipeline_status(phase="Notificações", detail="Enviando notícias qualificadas ao Telegram...")
            notifier = TelegramNotifier()
            sent_count = await dispatch_pending_notifications(notifier)
            logger.info(f"Background Scheduler: Successfully dispatched {sent_count} notifications.")
        except Exception as ne:
            logger.error(f"Background Scheduler: Telegram notification dispatch failed: {str(ne)}")
            
        update_pipeline_status(is_end=True)
    except Exception as e:
        logger.error(f"Background Scheduler: Editor Executivo failed: {str(e)}")
        update_pipeline_status(phase="Redação IA", error=str(e))


async def execute_news_cleanup():
    """
    Background job that removes news older than 20 days from the database.
    This keeps the database lean and ensures only recent, relevant content is served.
    """
    logger.info("Cleanup Scheduler: Starting old news purge (retention: 20 days)...")
    try:
        with get_db_session() as session:
            cutoff_date = datetime.utcnow() - timedelta(days=20)
            deleted_count = session.query(News).filter(
                News.created_at < cutoff_date
            ).delete(synchronize_session="fetch")
            logger.info(f"Cleanup Scheduler: Purged {deleted_count} news articles older than 20 days.")
    except Exception as e:
        logger.error(f"Cleanup Scheduler: News cleanup failed: {str(e)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events using context managers.
    """
    import os
    
    # Auto-create all tables at startup if they do not exist
    try:
        logger.info("Lifespan: Ensuring all database tables exist...")
        Base.metadata.create_all(bind=engine)
        
        # Dynamic migration: add translated_by_gemini column if it doesn't exist
        with engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE news ADD COLUMN translated_by_gemini BOOLEAN DEFAULT FALSE"))
                conn.commit()
                logger.info("Lifespan Database Migration: Added column 'translated_by_gemini' to news table.")
            except Exception as e:
                try:
                    conn.rollback()
                except:
                    pass
                logger.info(f"Lifespan Database Migration: Column 'translated_by_gemini' check: {str(e)}")
            
            # Migration for Editor Executivo columns
            editorial_cols = [
                ("editorial_status", "VARCHAR(50) DEFAULT 'pendente'"),
                ("editorial_title", "VARCHAR(255)"),
                ("editorial_summary", "TEXT"),
                ("editorial_category", "VARCHAR(100)"),
                ("editorial_tags", "TEXT"),
                ("meta_description", "TEXT"),
                ("editorial_scores", "JSON")
            ]
            for col_name, col_type in editorial_cols:
                try:
                    conn.execute(text(f"ALTER TABLE news ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
                    logger.info(f"Lifespan Database Migration: Added column '{col_name}' to news table.")
                except Exception as e:
                    try:
                        conn.rollback()
                    except:
                        pass
                    logger.info(f"Lifespan Database Migration: Column '{col_name}' check: {str(e)}")
    except Exception as e:
        logger.error(f"Lifespan: Failed to create database tables: {e}")

    disable_scheduler = os.getenv("DISABLE_SCHEDULER", "false").lower() == "true"
    
    if disable_scheduler:
        logger.info("Background Scheduler is disabled (DISABLE_SCHEDULER=true).")
        yield
        return
        
    logger.info("Initializing application lifespan with background scheduler...")
    
    # 1. Register the ingestion task (every 2 hours)
    scheduler.add_job(
        execute_scheduled_ingestion, 
        trigger="interval", 
        hours=2,
        id="ingestion_pipeline_job",
        replace_existing=True
    )
    
    # 1.5. Register the editor task (every 30 minutes)
    scheduler.add_job(
        execute_scheduled_editor,
        trigger="interval",
        minutes=30,
        id="editor_pipeline_job",
        replace_existing=True
    )
    
    # 2. Register the news cleanup task (daily at 03:00 AM UTC)
    scheduler.add_job(
        execute_news_cleanup,
        trigger="cron",
        hour=3,
        minute=0,
        id="news_cleanup_job",
        replace_existing=True
    )
    
    # 3. Start the Async scheduler
    scheduler.start()
    logger.info("Background Scheduler started successfully (ingestion + 20-day cleanup).")
    
    # Trigger initial ingestion in background on startup if DB is empty of news
    try:
        with get_db_session() as session:
            news_count = session.query(News).count()
        if news_count == 0:
            logger.info("Database is empty of news. Triggering initial ingestion on startup in background...")
            asyncio.create_task(execute_scheduled_ingestion())
    except Exception as e:
        logger.error(f"Startup check failed: {str(e)}")
        
    yield
    
    # 3. Shutdown scheduler gracefully on app close
    logger.info("Shutting down Background Scheduler...")
    scheduler.shutdown()
    logger.info("Background Scheduler stopped.")


# Initialize FastAPI app with lifespan events
app = FastAPI(
    title="Arandu News Portal API",
    description="API para portal de curadoria de notícias de tecnologia e empreendedorismo.",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for frontend cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Authentication Utilities
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a password against bcrypt or legacy SHA-256.
    """
    if len(hashed_password) == 64 and all(c in "0123456789abcdefABCDEF" for c in hashed_password):
        return hashlib.sha256(plain_password.encode("utf-8")).hexdigest() == hashed_password
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def generate_jwt_token(user_id: int, email: str, role: str) -> str:
    """
    Generates a secure JWT token valid for 24 hours.
    """
    import uuid
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "jti": uuid.uuid4().hex,
        "exp": datetime.utcnow() + timedelta(hours=24)
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def get_current_user_claims(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    Dependency that decodes and validates the Bearer token.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        # Verify the session is still active in the database
        with get_db_session() as session:
            active_session = session.query(ActiveSession).filter(ActiveSession.token == token).first()
            if not active_session:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Sessão inválida, expirada ou encerrada por limite de conexões."
                )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="O token de acesso expirou."
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou malformado."
        )


def require_admin_role(claims: dict = Depends(get_current_user_claims)) -> dict:
    """
    Dependency that guarantees the request comes from an authenticated Admin user.
    """
    if claims.get("role") != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado. Apenas administradores possuem acesso a este recurso."
        )
    return claims


# Pydantic Schemas
class LeadCreateRequest(BaseModel):
    name: str
    email: EmailStr
    whatsapp: str


class LeadResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    whatsapp: str
    created_at: datetime

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


class NewsItemResponse(BaseModel):
    id: int
    source_id: int
    source_name: Optional[str] = None
    original_title: str
    translated_title: Optional[str]
    link: str
    ai_summary: Optional[str]
    image_url: Optional[str]
    original_published_at: Optional[datetime]
    hash_title: str
    send_status: str
    created_at: datetime
    relevance_score: Optional[int] = None
    ai_justification: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    is_curated: Optional[bool] = False
    curated_at: Optional[datetime] = None
    
    # Editorial Executivo fields
    editorial_status: Optional[str] = "pendente"
    editorial_title: Optional[str] = None
    editorial_summary: Optional[str] = None
    editorial_category: Optional[str] = None
    editorial_tags: Optional[str] = None
    meta_description: Optional[str] = None
    editorial_scores: Optional[dict] = None

    class Config:
        from_attributes = True


class PaginatedNewsResponse(BaseModel):
    total: int
    page: int
    size: int
    results: List[NewsItemResponse]


# API Endpoints

@app.post("/api/auth/login", response_model=TokenResponse, summary="Autenticação de Usuários")
def login(payload: LoginRequest):
    """
    Authenticates users (Admins or Readers) and returns a JWT access token.
    Default admin account: admin@arandu.com.br / admin123
    """
    try:
        with get_db_session() as session:
            user = session.query(User).filter(User.email == payload.email).first()
            if not user or not verify_password(payload.password, user.password_hash):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="E-mail ou senha incorretos."
                )
            
            token = generate_jwt_token(user.id, user.email, user.role.value)
            
            # Clean up expired sessions first
            session.query(ActiveSession).filter(ActiveSession.expires_at <= datetime.utcnow()).delete()
            
            # Enforce max 3 active admin sessions if role is Admin
            if user.role == UserRole.ADMIN:
                active_admins = (
                    session.query(ActiveSession)
                    .join(User, User.id == ActiveSession.user_id)
                    .filter(User.role == UserRole.ADMIN)
                    .order_by(ActiveSession.created_at.asc())
                    .all()
                )
                if len(active_admins) >= 3:
                    # Kick out the oldest session(s) to keep at most 2 active, so the new one makes 3
                    to_remove = len(active_admins) - 2
                    for i in range(to_remove):
                        session.delete(active_admins[i])
            
            # Save the new active session
            expires_at = datetime.utcnow() + timedelta(hours=24)
            new_session = ActiveSession(
                token=token,
                user_id=user.id,
                expires_at=expires_at
            )
            session.add(new_session)
            
            return {"access_token": token, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno durante a autenticação."
        )


@app.post("/api/auth/logout", summary="Logout de Usuário")
def logout(
    claims: dict = Depends(get_current_user_claims),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Invalidates the current session by removing it from the active_sessions table.
    """
    token = credentials.credentials
    try:
        with get_db_session() as session:
            session.query(ActiveSession).filter(ActiveSession.token == token).delete()
            return {"status": "success", "message": "Desconectado com sucesso."}
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao realizar logout."
        )


@app.get("/api/noticias", response_model=PaginatedNewsResponse, summary="Consultar Notícias")
def get_news(
    page: int = Query(1, ge=1, description="Número da página (início em 1)"),
    size: int = Query(20, ge=1, le=100, description="Quantidade de registros por página"),
    source_id: Optional[int] = Query(None, description="Filtrar por ID da fonte de notícias"),
    send_status: Optional[SendStatus] = Query(None, description="Filtrar por status de envio (pendente, enviado_telegram, falha)"),
    editorial_status: Optional[str] = Query(None, description="Filtrar por status editorial (pendente, publicado, falha, processando)"),
    order_by: Optional[str] = Query("published", description="Ordenação: 'published' (data de publicação) ou 'created' (data de inserção/processamento)")
):
    """
    Returns a paginated list of curated news articles, filterable by source, telegram status, and editorial status.
    """
    offset = (page - 1) * size
    
    try:
        with get_db_session() as session:
            query = session.query(News)
            
            # Apply optional filters
            if source_id is not None:
                query = query.filter(News.source_id == source_id)
            if send_status is not None:
                query = query.filter(News.send_status == send_status)
            if editorial_status is not None:
                query = query.filter(News.editorial_status == editorial_status)
                
            # Count total results matching filters
            total = query.count()
            
            # Determine ordering clause
            order_clause = News.original_published_at.desc()
            if order_by == "created":
                order_clause = News.created_at.desc()
            
            # Retrieve paginated list ordered by original publish date descending or created_at descending
            results = (
                query.order_by(order_clause)
                .offset(offset)
                .limit(size)
                .all()
            )
            
            # Build source name lookup cache
            source_ids = list({item.source_id for item in results})
            sources_lookup = {}
            if source_ids:
                sources_data = session.query(Source).filter(Source.id.in_(source_ids)).all()
                sources_lookup = {s.id: s.name for s in sources_data}
            
            # Convert models to dictionaries with source_name included
            items = []
            for item in results:
                item_dict = NewsItemResponse.from_orm(item)
                item_dict.source_name = sources_lookup.get(item.source_id, "")
                items.append(item_dict)
            
            return {
                "total": total,
                "page": page,
                "size": size,
                "results": items
            }
            
    except Exception as e:
        logger.error(f"Error fetching news: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao obter a lista de notícias."
        )


@app.post("/api/admin/coleta-manual", summary="Forçar Execução do Pipeline (Admin)")
async def force_manual_collection(
    only_editor: bool = Query(False, description="Executar apenas o agente Editor Executivo"),
    admin_claims: dict = Depends(require_admin_role)
):
    """
    Protected Admin endpoint that runs the news crawler, AI processor, and notification dispatcher.
    """
    logger.info(f"Admin '{admin_claims.get('email')}' triggered manual collection (only_editor={only_editor}).")
    
    async def run_manual_pipeline():
        import os
        from core.status import update_pipeline_status
        is_only_editor = only_editor or os.getenv("ONLY_EDITOR", "false").lower() == "true"
        try:
            logger.info("Manual Pipeline: Starting execution...")
            await run_scraper(is_manual=True, only_editor=is_only_editor)
            
            if is_only_editor:
                logger.info("Manual Pipeline: ONLY_EDITOR mode is active. Skipping remaining stages.")
                return
            
            # Run Curador de Notícias agent
            try:
                logger.info("Manual Pipeline: Running Curador de Notícias...")
                curator = AgentOrchestrator()
                curator.run_curation_pipeline()
            except Exception as e:
                logger.error(f"Manual Pipeline: Curador failed: {str(e)}")
                update_pipeline_status(phase="Curadoria IA", error=str(e))
                raise e
            
            # Run Editor Executivo agent
            try:
                logger.info("Manual Pipeline: Running Editor Executivo...")
                editor = EditorExecutivoOrchestrator()
                editor.run_editorial_pipeline()
            except Exception as e:
                logger.error(f"Manual Pipeline: Editor Executivo failed: {str(e)}")
                update_pipeline_status(phase="Redação IA", error=str(e))
                raise e
            
            # Run Divulgação no Site
            try:
                logger.info("Manual Pipeline: Divulgando no Site...")
                update_pipeline_status(phase="Divulgação no Site", detail="Divulgando notícias qualificadas no portal...")
                with get_db_session() as session:
                    published_count = session.query(News).filter(News.editorial_status == "publicado").count()
                update_pipeline_status(phase="Divulgação no Site", detail=f"Divulgação concluída. Total de {published_count} notícias ativas.")
            except Exception as e:
                logger.error(f"Manual Pipeline: Divulgação failed: {str(e)}")
                update_pipeline_status(phase="Divulgação no Site", error=str(e))
                raise e
            
            # Run Notificações
            try:
                logger.info("Manual Pipeline: Enviando Notificações...")
                notifier = TelegramNotifier()
                await dispatch_pending_notifications(notifier)
            except Exception as e:
                logger.error(f"Manual Pipeline: Notificações failed: {str(e)}")
                update_pipeline_status(phase="Notificações", error=str(e))
                raise e
            
            update_pipeline_status(is_end=True)
            logger.info("Manual Pipeline: Finished successfully.")
        except Exception as e:
            logger.error(f"Manual Pipeline: Execution failed: {str(e)}")
            update_pipeline_status(error=str(e))
            raise e

    try:
        # Await the pipeline execution directly so that serverless functions (like Vercel)
        # do not freeze/terminate the process before it completes.
        await run_manual_pipeline()
        
        return {
            "status": "success",
            "message": "Pipeline de coleta, processamento e notificação executado com sucesso."
        }
    except Exception as e:
        logger.error(f"Manual collection trigger failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao acionar o pipeline manual: {str(e)}"
        )


@app.get("/api/cron/coleta", summary="Executar Coleta Periódica (Cron Vercel)")
async def vercel_cron_collection(
    authorization: Optional[str] = Header(None)
):
    """
    Cron endpoint triggered by Vercel Cron.
    Secured by checking the Vercel-provided CRON_SECRET environment variable.
    """
    import os
    cron_secret = os.getenv("CRON_SECRET")
    
    # If CRON_SECRET is configured, we verify the incoming request
    if cron_secret:
        expected_header = f"Bearer {cron_secret}"
        if not authorization or authorization != expected_header:
            logger.warning("Unauthorized cron trigger attempt blocked.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Acesso não autorizado para acionamento de cron."
            )
            
    logger.info("Vercel Cron triggered scheduled news collection.")
    
    async def run_cron_pipeline():
        from core.status import update_pipeline_status
        try:
            logger.info("Cron Pipeline: Starting execution...")
            await run_scraper()
            
            import os
            if os.getenv("ONLY_EDITOR", "false").lower() == "true":
                logger.info("Cron Pipeline: ONLY_EDITOR mode is active. Skipping remaining stages.")
                return
            
            # Run Curador de Notícias agent
            try:
                logger.info("Cron Pipeline: Running Curador de Notícias...")
                curator = AgentOrchestrator()
                curator.run_curation_pipeline()
            except Exception as e:
                logger.error(f"Cron Pipeline: Curador failed: {str(e)}")
                update_pipeline_status(phase="Curadoria IA", error=str(e))
                raise e
            
            # Run Editor Executivo agent
            try:
                logger.info("Cron Pipeline: Running Editor Executivo...")
                editor = EditorExecutivoOrchestrator()
                editor.run_editorial_pipeline()
            except Exception as e:
                logger.error(f"Cron Pipeline: Editor Executivo failed: {str(e)}")
                update_pipeline_status(phase="Redação IA", error=str(e))
                raise e
            
            # Run Divulgação no Site
            try:
                logger.info("Cron Pipeline: Divulgando no Site...")
                update_pipeline_status(phase="Divulgação no Site", detail="Divulgando notícias qualificadas no portal...")
                with get_db_session() as session:
                    published_count = session.query(News).filter(News.editorial_status == "publicado").count()
                update_pipeline_status(phase="Divulgação no Site", detail=f"Divulgação concluída. Total de {published_count} notícias ativas.")
            except Exception as e:
                logger.error(f"Cron Pipeline: Divulgação failed: {str(e)}")
                update_pipeline_status(phase="Divulgação no Site", error=str(e))
                raise e
            
            # Run Notificações
            try:
                logger.info("Cron Pipeline: Enviando Notificações...")
                notifier = TelegramNotifier()
                await dispatch_pending_notifications(notifier)
            except Exception as e:
                logger.error(f"Cron Pipeline: Notificações failed: {str(e)}")
                update_pipeline_status(phase="Notificações", error=str(e))
                raise e
            
            update_pipeline_status(is_end=True)
            logger.info("Cron Pipeline: Finished successfully.")
        except Exception as e:
            logger.error(f"Cron Pipeline: Execution failed: {str(e)}")
            update_pipeline_status(error=str(e))
            raise e

    try:
        # Await the pipeline execution directly so that serverless functions (like Vercel)
        # do not freeze/terminate the process before it completes.
        await run_cron_pipeline()
        return {
            "status": "success",
            "message": "Cron pipeline de coleta e processamento executado com sucesso."
        }
    except Exception as e:
        logger.error(f"Cron collection trigger failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao acionar a coleta via cron: {str(e)}"
        )


@app.post("/api/leads", summary="Registrar Lead da Landing Page")
def register_lead(payload: LeadCreateRequest):
    """
    Saves a captured lead (Name, Email, WhatsApp) to the database.
    Checks if the email is already registered to avoid duplication.
    """
    try:
        with get_db_session() as session:
            # Check if email is already registered
            existing_lead = session.query(Lead).filter(Lead.email == payload.email).first()
            if existing_lead:
                return {
                    "status": "success",
                    "message": "Lead já cadastrado anteriormente. Redirecionando...",
                    "already_exists": True
                }
            
            # Create new Lead record
            new_lead = Lead(
                name=payload.name,
                email=payload.email,
                whatsapp=payload.whatsapp
            )
            session.add(new_lead)
            return {
                "status": "success",
                "message": "Lead registrado com sucesso!"
            }
    except Exception as e:
        logger.error(f"Error registering lead: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao salvar dados de contato no banco de dados."
        )


@app.get("/api/admin/leads", response_model=List[LeadResponse], summary="Listar Leads Capturados (Admin)")
def get_leads(
    admin_claims: dict = Depends(require_admin_role)
):
    """
    Returns a list of all captured leads, ordered by creation date descending.
    Accessible only to authenticated Admins.
    """
    try:
        with get_db_session() as session:
            leads = session.query(Lead).order_by(Lead.created_at.desc()).all()
            return [LeadResponse.from_orm(lead) for lead in leads]
    except Exception as e:
        logger.error(f"Error fetching leads: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao obter a lista de leads."
        )


@app.get("/api/admin/stats/leads-daily", summary="Obter dados de evolução de leads (último mês)")
def get_leads_daily_stats(
    admin_claims: dict = Depends(require_admin_role)
):
    """
    Returns daily lead signups for the last 30 days (1 month).
    """
    try:
        from collections import defaultdict
        with get_db_session() as session:
            # Query all leads created in the last 30 days (1 month)
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            leads = session.query(Lead).filter(Lead.created_at >= thirty_days_ago).all()
            
            # Initialize daily counts
            daily_counts = defaultdict(int)
            
            # Pre-fill last 30 days with 0
            for i in range(30):
                day = (datetime.utcnow() - timedelta(days=i)).strftime("%d/%m")
                daily_counts[day] = 0
                
            # Aggregate counts
            for lead in leads:
                day_str = lead.created_at.strftime("%d/%m")
                if day_str in daily_counts:
                    daily_counts[day_str] += 1
            
            # Return sorted chronologically
            sorted_days = sorted(list(daily_counts.keys()), key=lambda d: datetime.strptime(d + f"/{datetime.utcnow().year}", "%d/%m/%Y"))
            return {
                "labels": sorted_days,
                "data": [daily_counts[day] for day in sorted_days]
            }
    except Exception as e:
        logger.error(f"Error fetching daily lead stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao obter estatísticas de leads."
        )


@app.get("/api/admin/stats/news-categories", summary="Obter estatísticas de distribuição de notícias por nicho")
def get_news_categories_stats(
    admin_claims: dict = Depends(require_admin_role)
):
    """
    Returns counts of news articles grouped by category.
    Maps sources to categories matching frontend rules.
    """
    try:
        with get_db_session() as session:
            news_items = session.query(News).all()
            
            # Hardcoded source to category map matching the frontend mapping
            source_map = {
                "Canaltech": "tecnologia",
                "TI Inside": "tecnologia",
                "Olhar Digital": "tecnologia",
                "Tecmundo": "tecnologia",
                "Tecnoblog": "tecnologia",
                "G1 Tecnologia": "tecnologia",
                "TechCrunch": "tecnologia",
                "Wired": "tecnologia",
                "MIT Technology Review": "tecnologia",
                "Google Research Blog": "tecnologia",
                "AWS News Blog": "investimentos",
                "VentureBeat": "investimentos",
                "Época Negócios": "investimentos",
                "G1 Empreendedorismo": "empreendedorismo",
                "Paul Graham Essays": "empreendedorismo",
                "Stanford eCorner": "empreendedorismo",
                "Harvard Business Review": "empreendedorismo",
                "MIT Sloan Management Review": "empreendedorismo",
                "Knowledge at Wharton": "empreendedorismo"
            }
            
            categories = {"tecnologia": 0, "empreendedorismo": 0, "investimentos": 0}
            
            # In order to query Source names, we need to load Sources and build a cache
            sources = {s.id: s.name for s in session.query(Source).all()}
            
            for item in news_items:
                src_name = sources.get(item.source_id, "")
                cat = source_map.get(src_name, "tecnologia")
                if cat in categories:
                    categories[cat] += 1
                    
            return {
                "labels": ["Tecnologia", "Empreendedorismo", "Investimentos"],
                "data": [categories["tecnologia"], categories["empreendedorismo"], categories["investimentos"]]
            }
    except Exception as e:
        logger.error(f"Error fetching news category stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao obter estatísticas de categorias."
        )


@app.get("/api/admin/stats/gemini-usage", summary="Obter uso diário do Gemini")
def get_gemini_usage_stats(
    admin_claims: dict = Depends(require_admin_role)
):
    """
    Returns the daily usage, quota limit, and rate limit status for the Gemini API.
    """
    try:
        from core.processor import get_gemini_usage_today, get_rate_limit_info
        usage = get_gemini_usage_today()
        rate_limit = get_rate_limit_info()
        return {
            "usage": usage,
            "limit": settings.GEMINI_DAILY_LIMIT,
            "has_key": bool(settings.GEMINI_API_KEY),
            "rate_limit": rate_limit
        }
    except Exception as e:
        logger.error(f"Error fetching Gemini usage stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao obter estatísticas de uso do Gemini."
        )


def check_and_reset_stuck_pipeline(session, status_entry):
    """
    Checks if the pipeline status has been stuck in the 'running' state for more than 2 minutes.
    Backed by a 15-second heartbeat thread in core/status.py, this detects crashed
    or frozen serverless/VPS processes quickly without affecting slow runs.
    """
    if status_entry and status_entry.status == "running":
        from datetime import datetime, timedelta
        last_active = status_entry.updated_at or status_entry.last_run_at
        if last_active and datetime.utcnow() - last_active > timedelta(minutes=2):
            logger.warning("Pipeline status was stuck in 'running' for >2 minutes (heartbeat stopped). Auto-resetting to failed.")
            status_entry.status = "failed"
            status_entry.current_phase = None
            status_entry.current_detail = None
            status_entry.last_error = "Timeout: O pipeline foi interrompido (provavelmente pelo limite de execução de 10s da Vercel)."
            session.commit()


@app.get("/api/admin/pipeline-status", summary="Obter status em tempo real da IA e Scraper")
def get_pipeline_status(
    admin_claims: dict = Depends(require_admin_role)
):
    """
    Returns the real-time status of the news scraper / AI pipeline.
    """
    try:
        with get_db_session() as session:
            status_entry = session.query(PipelineStatus).filter(PipelineStatus.id == 1).first()
            if not status_entry:
                return {
                    "status": "idle",
                    "current_phase": None,
                    "current_detail": None,
                    "last_run_at": None,
                    "last_success_at": None,
                    "last_duration_seconds": None,
                    "last_error": None,
                    "updated_at": None
                }
            
            check_and_reset_stuck_pipeline(session, status_entry)
            
            return {
                "status": status_entry.status,
                "current_phase": status_entry.current_phase,
                "current_detail": status_entry.current_detail,
                "last_run_at": status_entry.last_run_at.isoformat() + "Z" if status_entry.last_run_at else None,
                "last_success_at": status_entry.last_success_at.isoformat() + "Z" if status_entry.last_success_at else None,
                "last_duration_seconds": status_entry.last_duration_seconds,
                "last_error": status_entry.last_error,
                "updated_at": status_entry.updated_at.isoformat() + "Z" if status_entry.updated_at else None
            }
    except Exception as e:
        logger.error(f"Error fetching pipeline status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao obter o status do pipeline."
        )


@app.get("/api/pipeline-status", summary="Obter status em tempo real da IA e Scraper (Público)")
def get_public_pipeline_status():
    """
    Returns the real-time status of the news scraper / AI pipeline.
    Accessible publicly to show what the AI is doing.
    """
    try:
        with get_db_session() as session:
            status_entry = session.query(PipelineStatus).filter(PipelineStatus.id == 1).first()
            if not status_entry:
                return {
                    "status": "idle",
                    "current_phase": None,
                    "current_detail": None,
                    "last_run_at": None,
                    "last_success_at": None,
                    "last_duration_seconds": None,
                    "last_error": None,
                    "updated_at": None
                }
            
            check_and_reset_stuck_pipeline(session, status_entry)
            
            return {
                "status": status_entry.status,
                "current_phase": status_entry.current_phase,
                "current_detail": status_entry.current_detail,
                "last_run_at": status_entry.last_run_at.isoformat() + "Z" if status_entry.last_run_at else None,
                "last_success_at": status_entry.last_success_at.isoformat() + "Z" if status_entry.last_success_at else None,
                "last_duration_seconds": status_entry.last_duration_seconds,
                "last_error": status_entry.last_error,
                "updated_at": status_entry.updated_at.isoformat() + "Z" if status_entry.updated_at else None
            }
    except Exception as e:
        logger.error(f"Error fetching public pipeline status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao obter o status do pipeline."
        )


@app.get("/api/debug-gemini", summary="Debug Gemini API Connection")
def debug_gemini():
    """
    Temporary debug endpoint to test Gemini API key and connection.
    """
    key = settings.GEMINI_API_KEY
    if not key:
        return {
            "status": "error",
            "message": "GEMINI_API_KEY is not defined in environment variables."
        }
    
    # Mask key for security
    masked_key = key[:6] + "..." + key[-4:] if len(key) > 10 else "too short"
    
    try:
        from core.processor import call_gemini_api
        response_text = call_gemini_api(
            prompt="Hello. Respond with 'API Key is working' if you see this.",
            max_tokens=30,
            temperature=0.0
        )
        return {
            "status": "success",
            "masked_key": masked_key,
            "response": response_text.strip() if response_text else None
        }
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "masked_key": masked_key,
            "error_type": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc()
        }


@app.get("/api/health", summary="Health Check")
def health_check():
    """
    Checks if API and database connection are working.
    """
    try:
        with get_db_session() as session:
            # Simple query to check connection (database-agnostic)
            session.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database_error": str(e)}


@app.get("/", summary="Servir index.html")
@app.get("/index.html", summary="Servir index.html")
def read_index():
    return FileResponse("index.html")

@app.get("/noticias.html", summary="Servir noticias.html")
def read_noticias():
    return FileResponse("noticias.html")

@app.get("/admin.html", summary="Servir admin.html")
def read_admin():
    return FileResponse("admin.html")

@app.get("/favicon.ico", summary="Servir favicon")
def read_favicon():
    svg_content = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="none"><path d="M50 5L92 85H74L50 37L26 85H8L50 5Z" fill="#C5A85C"/><path d="M37 60H63L68 70H32L37 60Z" fill="#E8D098"/></svg>"""
    return Response(content=svg_content, media_type="image/svg+xml")


if __name__ == "__main__":
    import uvicorn
    # Start webserver on port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
