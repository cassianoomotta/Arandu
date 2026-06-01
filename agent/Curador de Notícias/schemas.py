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
class CurationItem(BaseModel):
    id: int
    status: str = Field(..., description="APROVADA ou REPROVADA. Adote uma postura conservadora e reprove se houver dúvida.")
    justificativa: str = Field(..., description="Justificativa concisa da classificação (máximo 15 palavras).")
    categoria_identificada: str = Field(..., description="Categoria principal (deve ser exatamente uma das 16 listadas).")
    score: int = Field(..., description="Score de relevância de 1 a 5.")

class CurationResponse(BaseModel):
    items: List[CurationItem]

def get_gemini_schema(model_class) -> dict:
    """
    Returns a clean, inlined JSON schema dictionary formatted for Gemini's responseSchema.
    Compatible with both Pydantic v1 and v2. Resolves all nested $ref references.
    """
    if hasattr(model_class, "model_json_schema"):
        schema = model_class.model_json_schema()
    else:
        schema = model_class.schema()
        
    import copy
    schema = copy.deepcopy(schema)
    
    # Extract definitions
    defs = schema.pop("$defs", {})
    if not defs and "definitions" in schema:
        defs = schema.pop("definitions", {})
        
    def resolve(val):
        if isinstance(val, dict):
            if "$ref" in val:
                ref_path = val["$ref"]
                ref_name = ref_path.split("/")[-1]
                if ref_name in defs:
                    resolved_def = resolve(defs[ref_name])
                    res = copy.deepcopy(resolved_def)
                    for k, v in val.items():
                        if k != "$ref" and k not in res:
                            res[k] = v
                    return res
            return {k: resolve(v) for k, v in val.items()}
        elif isinstance(val, list):
            return [resolve(item) for item in val]
        return val
        
    cleaned_schema = resolve(schema)
    
    # Remove metadata at the top level
    for key in ["title", "description", "$schema"]:
        cleaned_schema.pop(key, None)
        
    return cleaned_schema
