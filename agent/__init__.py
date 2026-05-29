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

# Dynamic import for "Editor Executivo" agent
_editor_orch = importlib.import_module("agent.Editor Executivo.orchestrator")
EditorExecutivoOrchestrator = _editor_orch.EditorExecutivoOrchestrator

__all__ = [
    "AgentOrchestrator",
    "agent_settings",
    "LocalFilter",
    "calculate_local_heuristic_score",
    "EditorExecutivoOrchestrator"
]
