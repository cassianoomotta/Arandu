import os
import httpx
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("GEMINI_API_KEY")
models = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash"
]

payload = {
    "contents": [{
        "parts": [{"text": "Hello, this is a test. Please reply in one word."}]
    }]
}
headers = {"Content-Type": "application/json"}

for model in models:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    print(f"\n--- Testing model: {model} ---")
    try:
        response = httpx.post(url, json=payload, headers=headers)
        print("Status Code:", response.status_code)
        if response.status_code == 200:
            print("Success! Response JSON:", response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip())
        else:
            print("Error JSON:", response.json())
    except Exception as e:
        print("Error:", e)
