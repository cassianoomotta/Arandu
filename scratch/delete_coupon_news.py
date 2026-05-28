"""
Database Maintenance Script: Purge all promotional and coupon news articles.
Cleans up the database by deleting any existing articles matching promotion,
coupon, discount, sale, or deals keywords in their titles or links.
"""
import sys
sys.path.append('.')

from database.connection import get_db_session
from database.models import News

COUPON_KEYWORDS = [
    "cupom", "cupons", "promoção", "promoções", "promocional", "desconto", "descontos", 
    "oferta", "ofertas", "coupon", "coupons", "promo", "promos", "discount", "discounts", 
    "affiliate", "afiliado", "afiliados", "compre", "comprar", "compras", 
    "shop", "store", "sale", "liquidação", "queima", "estoque", "outlet"
]

def contains_coupon_indicator(text: str) -> bool:
    if not text:
        return False
    # Normalize words by splitting
    import re
    words = set(re.sub(r'[^\w\s]', ' ', text.lower()).split())
    for kw in COUPON_KEYWORDS:
        if kw in words:
            return True
    return False

def contains_coupon_indicator_substring(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower()
    for kw in COUPON_KEYWORDS:
        if kw in text_lower:
            return True
    return False

def main():
    print("Connecting to database and fetching news articles...")
    try:
        with get_db_session() as session:
            all_news = session.query(News).all()
            print(f"Total news articles found in DB: {len(all_news)}")
            
            to_delete = []
            for item in all_news:
                # Check translated title
                title_has_coupon = contains_coupon_indicator(item.translated_title) or contains_coupon_indicator(item.original_title)
                # Check substrings in link to capture URLs like /surfshark-coupon/
                link_has_coupon = contains_coupon_indicator_substring(item.link)
                
                if title_has_coupon or link_has_coupon:
                    to_delete.append(item)
                    
            if not to_delete:
                print("No coupon/promo news found in the database. Nothing to delete!")
                return
                
            print(f"\nFound {len(to_delete)} articles containing coupon or promotional patterns:")
            for idx, item in enumerate(to_delete, 1):
                title = item.translated_title or item.original_title
                print(f"[{idx}] ID: {item.id} | Title: '{title[:70]}...'")
                print(f"    Link: {item.link}")
                
            # Perform deletion
            deleted_count = 0
            for item in to_delete:
                session.delete(item)
                deleted_count += 1
                
            session.commit()
            print(f"\nSuccessfully deleted {deleted_count} promotional articles from the database.")
            
    except Exception as e:
        print(f"Error during database maintenance: {str(e)}")

if __name__ == "__main__":
    main()
