import os

class AgentSettings:
    # Batch sizes
    PHASE1_BATCH_SIZE: int = 20  # Number of news to classify at once in Phase 1
    TOP_N_SELECTION: int = 50   # How many news pass from Phase 1 to Phase 2
    FINAL_MIN_NEWS: int = 5     # Target minimum number of news to publish daily
    FINAL_MAX_NEWS: int = 7     # Absolute maximum number of news to publish daily
    EXCEPTIONAL_SCORE_THRESHOLD: int = 90  # Min score for 6th and 7th news
    
    # Heuristics & Local filter thresholds
    SIMILARITY_THRESHOLD: float = 0.8  # Threshold for SequenceMatcher deduplication
    MIN_TITLE_LENGTH: int = 10  # Minimum character count for titles to process
    
    # Categories of interest (exactly 16 categories)
    CATEGORIES: list[str] = [
        "Inteligência Artificial",
        "Tecnologia",
        "Ciência",
        "Robótica",
        "Biotecnologia",
        "Computação Quântica",
        "Saúde e Inovação",
        "Energia",
        "Espaço",
        "Startups",
        "Investimentos",
        "Mercado",
        "Negócios",
        "Empreendedorismo",
        "Transformação Digital",
        "Cibersegurança"
    ]
    
    # Priority Levels
    PRIORITIES: list[str] = ["Alta", "Média", "Baixa"]

agent_settings = AgentSettings()
