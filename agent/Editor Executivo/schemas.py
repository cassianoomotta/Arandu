from pydantic import BaseModel, Field
from typing import List

class EditorialScores(BaseModel):
    clarity_score: int = Field(..., description="Score de clareza e legibilidade (0-100)")
    impact_score: int = Field(..., description="Score de impacto no mercado ou sociedade (0-100)")
    innovation_score: int = Field(..., description="Score de inovação técnica descrita (0-100)")

class ExecutiveSummary(BaseModel):
    what_happened: str = Field(..., description="O que aconteceu? Explicação concisa da notícia.")
    why_it_matters: str = Field(..., description="Por que isso importa? Contexto e relevância.")
    possible_impacts: str = Field(..., description="Possíveis impactos no setor ou mercado.")
    key_points: List[str] = Field(..., description="3 a 5 pontos-chave essenciais.")

class EditorialResponse(BaseModel):
    headline: str = Field(..., description="Título otimizado e jornalístico, livre de clickbaits e sensacionalismo.")
    summary: ExecutiveSummary = Field(..., description="Resumo executivo estruturado.")
    category: str = Field(..., description="Categoria exata da notícia (ex: IA, Startups, Pesquisa Científica, Mercado, Tecnologia, Open Source, Hardware, Cloud, Cibersegurança).")
    tags: List[str] = Field(..., description="Lista de 3 a 5 tags focadas em SEO.")
    meta_description: str = Field(..., description="Meta description atraente para SEO com até 160 caracteres.")
    scores: EditorialScores = Field(..., description="Pontuações editoriais calculadas pela IA.")
