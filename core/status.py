import logging
import time
from datetime import datetime
from database.connection import get_db_session
from database.models import PipelineStatus

logger = logging.getLogger("pipeline_status")

# Global track for run start time for duration calculation
_run_start_time = None

def update_pipeline_status(
    status: str = None,
    phase: str = None,
    detail: str = None,
    error: str = None,
    is_start: bool = False,
    is_end: bool = False,
    duration: float = None
):
    """
    Updates the global pipeline execution state in the database.
    """
    global _run_start_time
    try:
        with get_db_session() as session:
            # Check if record with ID=1 exists (or create it)
            # Use raw query or session query. Let's use session query
            state = session.query(PipelineStatus).filter(PipelineStatus.id == 1).first()
            if not state:
                state = PipelineStatus(id=1, status="idle")
                session.add(state)
                session.flush() # Populate default values
            
            if is_start:
                _run_start_time = time.time()
                state.status = "running"
                state.current_phase = phase or "Iniciando"
                state.current_detail = detail or "Preparando pipeline de coleta..."
                state.last_run_at = datetime.utcnow()
                state.last_error = None
            elif error:
                state.status = "failed"
                state.current_phase = None
                state.current_detail = None
                state.last_error = error
                if _run_start_time:
                    state.last_duration_seconds = time.time() - _run_start_time
                    _run_start_time = None
            elif is_end:
                state.status = "idle"
                state.current_phase = None
                state.current_detail = None
                state.last_success_at = datetime.utcnow()
                if duration:
                    state.last_duration_seconds = duration
                elif _run_start_time:
                    state.last_duration_seconds = time.time() - _run_start_time
                _run_start_time = None
            else:
                if status:
                    state.status = status
                if phase is not None:
                    state.current_phase = phase
                if detail is not None:
                    state.current_detail = detail
            
            # get_db_session context manager commits automatically
            logger.debug(f"Pipeline status updated in DB: {state.status} | {state.current_phase} | {state.current_detail}")
    except Exception as e:
        logger.error(f"Failed to update pipeline status in DB: {e}")
