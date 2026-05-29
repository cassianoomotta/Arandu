import importlib

# Dynamic import to handle spaces/accents in subdirectory name "Curador de Notícias"
_orchestrator = importlib.import_module("agent.Curador de Notícias.orchestrator")
_config = importlib.import_module("agent.Curador de Notícias.config")
_filters = importlib.import_module("agent.Curador de Notícias.filters")
_utils = importlib.import_module("agent.Curador de Notícias.utils")

AgentOrchestrator = _orchestrator.AgentOrchestrator
agent_settings = _config.agent_settings
LocalFilter = _filters.LocalFilter
calculate_local_heuristic_score = _utils.calculate_local_heuristic_score

__all__ = [
    "AgentOrchestrator",
    "agent_settings",
    "LocalFilter",
    "calculate_local_heuristic_score"
]
