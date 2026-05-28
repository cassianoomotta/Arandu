import os
import sys
import time

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.processor import translate_existing_news_with_gemini

def main():
    print("Starting database translation & summary healing pass...")
    start_time = time.time()
    translate_existing_news_with_gemini(start_time, timeout_limit=300.0)
    print(f"Healing pass complete. Time elapsed: {time.time() - start_time:.2f}s")

if __name__ == "__main__":
    main()
