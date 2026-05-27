import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import List, Optional

import jwt
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy import func

from database.config import settings
from database.connection import get_db_session
from database.models import News, Source, User, UserRole, SendStatus, Lead
from core.scraper import main as run_scraper
from core.notifier import TelegramNotifier, dispatch_pending_notifications

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
    Background job that runs the full news ingestion and notification dispatch pipeline.
    """
    logger.info("Background Scheduler: Starting full news curation cycle...")
    try:
        # 1. Run scraping, translation, and AI summarization
        await run_scraper()
        
        # 2. Dispatch pending notifications via TelegramNotifier strategy
        notifier = TelegramNotifier()
        await dispatch_pending_notifications(notifier)
        
        logger.info("Background Scheduler: Full news curation cycle completed successfully.")
    except Exception as e:
        logger.error(f"Background Scheduler: News curation cycle failed: {str(e)}")


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
    logger.info("Initializing application lifespan...")
    
    # 1. Register the ingestion task (every 15 minutes)
    scheduler.add_job(
        execute_scheduled_ingestion, 
        trigger="interval", 
        minutes=15,
        id="ingestion_pipeline_job",
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

def verify_sha256_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a password against a SHA-256 hash.
    """
    return hashlib.sha256(plain_password.encode("utf-8")).hexdigest() == hashed_password


def generate_jwt_token(user_id: int, email: str, role: str) -> str:
    """
    Generates a secure JWT token valid for 24 hours.
    """
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
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
    original_title: str
    translated_title: Optional[str]
    link: str
    ai_summary: Optional[str]
    image_url: Optional[str]
    original_published_at: Optional[datetime]
    hash_title: str
    send_status: str
    created_at: datetime

    class Config:
        from_attributes = True


class PaginatedNewsResponse(BaseModel):
    total: int
    page: int
    size: int
    results: List[NewsItemResponse]


# API Endpoints

@app.post("/auth/login", response_model=TokenResponse, summary="Autenticação de Usuários")
def login(payload: LoginRequest):
    """
    Authenticates users (Admins or Readers) and returns a JWT access token.
    Default admin account: admin@arandu.com.br / admin123
    """
    try:
        with get_db_session() as session:
            user = session.query(User).filter(User.email == payload.email).first()
            if not user or not verify_sha256_password(payload.password, user.password_hash):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="E-mail ou senha incorretos."
                )
            
            token = generate_jwt_token(user.id, user.email, user.role.value)
            return {"access_token": token, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno durante a autenticação."
        )


@app.get("/noticias", response_model=PaginatedNewsResponse, summary="Consultar Notícias")
def get_news(
    page: int = Query(1, ge=1, description="Número da página (início em 1)"),
    size: int = Query(20, ge=1, le=100, description="Quantidade de registros por página"),
    source_id: Optional[int] = Query(None, description="Filtrar por ID da fonte de notícias"),
    send_status: Optional[SendStatus] = Query(None, description="Filtrar por status de envio (pendente, enviado_telegram, falha)")
):
    """
    Returns a paginated list of curated news articles, filterable by source and telegram status.
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
                
            # Count total results matching filters
            total = query.count()
            
            # Retrieve paginated list ordered by original publish date descending
            results = (
                query.order_by(News.original_published_at.desc())
                .offset(offset)
                .limit(size)
                .all()
            )
            
            # Convert models to dictionaries before session closes to avoid LazyLoading errors
            items = [NewsItemResponse.from_orm(item) for item in results]
            
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


@app.post("/admin/coleta-manual", summary="Forçar Execução do Pipeline (Admin)")
async def force_manual_collection(
    admin_claims: dict = Depends(require_admin_role)
):
    """
    Protected Admin endpoint that runs the news crawler, AI processor, and notification dispatcher.
    """
    logger.info(f"Admin '{admin_claims.get('email')}' triggered manual collection.")
    
    async def run_manual_pipeline():
        try:
            logger.info("Manual Pipeline: Starting execution...")
            await run_scraper()
            notifier = TelegramNotifier()
            await dispatch_pending_notifications(notifier)
            logger.info("Manual Pipeline: Finished successfully.")
        except Exception as e:
            logger.error(f"Manual Pipeline: Execution failed: {str(e)}")

    try:
        # Trigger full pipeline asynchronously as a background task
        asyncio.create_task(run_manual_pipeline())
        
        return {
            "status": "success",
            "message": "Pipeline de coleta, processamento e notificação disparado em segundo plano com sucesso."
        }
    except Exception as e:
        logger.error(f"Manual collection trigger failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao acionar o pipeline manual: {str(e)}"
        )


@app.post("/leads", summary="Registrar Lead da Landing Page")
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


@app.get("/admin/leads", response_model=List[LeadResponse], summary="Listar Leads Capturados (Admin)")
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


@app.get("/health", summary="Health Check")
def health_check():
    """
    Checks if API and database connection are working.
    """
    try:
        with get_db_session() as session:
            # Simple query to check connection
            session.execute(func.now())
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database_error": str(e)}


if __name__ == "__main__":
    import uvicorn
    # Start webserver on port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
