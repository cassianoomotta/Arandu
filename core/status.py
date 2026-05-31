import logging
import time
import threading
from datetime import datetime
from database.connection import get_db_session
from database.models import PipelineStatus

logger = logging.getLogger("pipeline_status")

# Global track for run start time for duration calculation
_run_start_time = None

# Heartbeat thread variables
_heartbeat_thread = None
_heartbeat_stop_event = None

def _run_heartbeat():
    logger.info("Heartbeat thread started.")
    while _heartbeat_stop_event and not _heartbeat_stop_event.is_set():
        # Sleep for 15 seconds, checking the stop event periodically (every 0.5s)
        for _ in range(30):
            if _heartbeat_stop_event is None or _heartbeat_stop_event.is_set():
                break
            time.sleep(0.5)
        if _heartbeat_stop_event is None or _heartbeat_stop_event.is_set():
            break
            
        # Update the updated_at timestamp in the database to signal life
        try:
            with get_db_session() as session:
                state = session.query(PipelineStatus).filter(PipelineStatus.id == 1).first()
                if state and state.status == "running":
                    # Force updated_at update
                    state.updated_at = datetime.utcnow()
                    session.commit()
                    logger.debug("Heartbeat: pipeline status updated_at touched.")
                else:
                    # If status is no longer running, stop the heartbeat thread
                    break
        except Exception as e:
            logger.error(f"Heartbeat thread failed to touch status: {e}")
    logger.info("Heartbeat thread stopped.")

def start_heartbeat():
    global _heartbeat_thread, _heartbeat_stop_event
    stop_heartbeat() # Make sure any previous heartbeat is stopped
    
    _heartbeat_stop_event = threading.Event()
    _heartbeat_thread = threading.Thread(target=_run_heartbeat, daemon=True, name="PipelineHeartbeat")
    _heartbeat_thread.start()

def stop_heartbeat():
    global _heartbeat_thread, _heartbeat_stop_event
    if _heartbeat_stop_event:
        _heartbeat_stop_event.set()
    _heartbeat_thread = None
    _heartbeat_stop_event = None

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
                start_heartbeat()
            elif error:
                state.status = "failed"
                # Keep state.current_phase to show which phase failed on the frontend
                state.last_error = error
                if _run_start_time:
                    state.last_duration_seconds = time.time() - _run_start_time
                    _run_start_time = None
                stop_heartbeat()
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
                stop_heartbeat()
            else:
                if status:
                    state.status = status
                    if status != "running":
                        stop_heartbeat()
                    else:
                        start_heartbeat()
                if phase is not None:
                    state.current_phase = phase
                if detail is not None:
                    state.current_detail = detail
            
            # get_db_session context manager commits automatically
            logger.debug(f"Pipeline status updated in DB: {state.status} | {state.current_phase} | {state.current_detail}")
    except Exception as e:
        logger.error(f"Failed to update pipeline status in DB: {e}")
