from pydantic import BaseModel, Field
from typing import List

class Phase1Item(BaseModel):
    id: int
    score: int = Field(..., description="Score de relevância preliminar de 0 a 10")

class Phase1Response(BaseModel):
    classifications: List[Phase1Item]


class Phase2Item(BaseModel):
    id: int
    score_relevance: int = Field(..., description="Score refinado de relevância de 0 a 100")
    justification: str = Field(..., description="Justificativa curta em português com no máximo 15 palavras explicando a relevância")
    category: str = Field(..., description="Categoria exata: Tecnologia, IA/Automação, Mercado/Investimentos, Academia/Ciência ou Descobertas Tecnológicas")
    priority: str = Field(..., description="Nível de prioridade: Alta, Média ou Baixa")

class Phase2Response(BaseModel):
    items: List[Phase2Item]


def get_gemini_schema(model_class) -> dict:
    """
    Returns a clean JSON schema dictionary formatted for Gemini's responseSchema.
    Compatible with both Pydantic v1 and v2.
    """
    if hasattr(model_class, "model_json_schema"):
        schema = model_class.model_json_schema()
    else:
        schema = model_class.schema()
        
    # Clean up schemas to remove Pydantic-specific definitions that can confuse the API
    def clean_schema(s: dict) -> dict:
        if not isinstance(s, dict):
            return s
        cleaned = {}
        for k, v in s.items():
            if k in ["title", "description", "$schema", "definitions", "$defs"]:
                # We can keep description in properties, but remove title/description/refs at top level
                continue
            if isinstance(v, dict):
                cleaned[k] = clean_schema(v)
            elif isinstance(v, list):
                cleaned[k] = [clean_schema(item) if isinstance(item, dict) else item for item in v]
            else:
                cleaned[k] = v
        return cleaned

    # Gemini expects types in uppercase for REST API sometimes, but standard JSON schema is lowercase.
    # To be extremely safe, we provide standard lowercase schema which is universally supported
    # by v1beta API generateContent payload.
    return schema
