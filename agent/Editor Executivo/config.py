class EditorSettings:
    DEFAULT_MODELS: list[str] = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-1.5-flash"]
    
    # Text compression constraints
    MIN_COMPRESSION_WORDS: int = 800
    MAX_COMPRESSION_WORDS: int = 1200
    
    # Approved editorial categories
    CATEGORIES: list[str] = [
        "IA",
        "Startups",
        "Pesquisa Científica",
        "Mercado",
        "Tecnologia",
        "Open Source",
        "Hardware",
        "Cloud",
        "Cibersegurança"
    ]
    
    # SequenceMatcher similarity threshold for topic deduplication
    THEME_SIMILARITY_THRESHOLD: float = 0.75

editor_settings = EditorSettings()
