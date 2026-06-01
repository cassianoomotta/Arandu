import os
import sys

# Add workspace directory to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock FastAPI Query and other imports if needed
from main import get_news

try:
    # Explicitly pass None for FastAPI Query parameters
    response = get_news(page=1, size=100, source_id=None, send_status=None)
    print("Total in response:", response["total"])
    print("Page:", response["page"])
    print("Size:", response["size"])
    print("Number of results:", len(response["results"]))
    print("Results:")
    for item in response["results"]:
        print(f"ID: {item.id} | Title: {item.original_title[:50]} | Score: {item.relevance_score} | Status: {item.editorial_status}")
except Exception as e:
    import traceback
    traceback.print_exc()
