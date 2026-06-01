import os
import httpx
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("GEMINI_API_KEY")
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"

try:
    print("Listing available models from Google API...")
    response = httpx.get(url)
    print("Status Code:", response.status_code)
    data = response.json()
    for m in data.get("models", []):
        print(f"Model Name: {m['name']} | Display Name: {m['displayName']} | Supported Methods: {m['supportedGenerationMethods']}")
except Exception as e:
    print("Error:", e)
