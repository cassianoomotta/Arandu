import os
import sys
import httpx
import json

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from database.config import settings

def test():
    key = settings.GEMINI_API_KEY
    model = "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    
    system_prompt = (
        "Você é um analista de inteligência de negócios. "
        "Gere EXATAMENTE 3 bullet points de resumo executivo sobre a notícia, "
        "focados em tecnologia e oportunidades de negócios. "
        "REGRAS OBRIGATÓRIAS:\n"
        "1. Comece DIRETAMENTE com o primeiro bullet point usando hífen '-'.\n"
        "2. NÃO escreva introdução, preâmbulo, saudação ou qualquer texto antes dos bullets.\n"
        "3. NÃO escreva 'Aqui está', 'Segue', 'Resumo executivo' ou qualquer frase introdutória.\n"
        "4. Cada bullet deve ter no máximo 2 frases.\n"
        "5. Use português brasileiro.\n"
        "EXEMPLO DE FORMATO CORRETO:\n"
        "- Primeiro ponto sobre o impacto tecnológico.\n"
        "- Segundo ponto sobre oportunidade de negócio.\n"
        "- Terceiro ponto sobre tendência ou desafio."
    )
    user_prompt = "Título da notícia: Estudo da Unesp com a NASA mapeia destruição em enchentes"
    
    payload = {
        "contents": [{
            "parts": [{"text": user_prompt}]
        }],
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 2048
        }
    }
    
    print(f"Calling Gemini API with model: {model}...")
    headers = {"Content-Type": "application/json"}
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, json=payload, headers=headers)
        print("Status code:", response.status_code)
        if response.status_code == 200:
            data = response.json()
            print("Full response JSON:")
            print(json.dumps(data, indent=2))
        else:
            print(response.text)

if __name__ == "__main__":
    test()
