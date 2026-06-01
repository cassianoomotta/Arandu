import requests

url = "http://localhost:8000/api/noticias?page=1&size=100"
try:
    r = requests.get(url)
    print("Status code:", r.status_code)
    if r.status_code == 200:
        data = r.json()
        print("Total results returned from API:", len(data.get("results", [])))
        print("Total count in API metadata:", data.get("total"))
        print("Titles:")
        for item in data.get("results", []):
            print(f"- {item.get('id')}: {item.get('original_title')[:60]} (Editorial: {item.get('editorial_status')})")
except Exception as e:
    print("Error calling API:", e)
