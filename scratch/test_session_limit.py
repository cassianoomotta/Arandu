import os
import sys

# Add root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import get_db_session, engine
from database.models import Base, User, UserRole, ActiveSession
from main import login, LoginRequest

# Ensure tables are created
Base.metadata.create_all(bind=engine)

def run_test():
    print("Starting session limit test...")
    with get_db_session() as session:
        # Check or create an Admin user
        admin_email = "admin@arandu.com.br"
        admin = session.query(User).filter(User.email == admin_email).first()
        if not admin:
            import hashlib
            password_hash = hashlib.sha256("Aranduadmin".encode("utf-8")).hexdigest()
            admin = User(name="Admin Test", email=admin_email, password_hash=password_hash, role=UserRole.ADMIN)
            session.add(admin)
            session.commit()
            print("Created test admin user.")

        # Clear existing active sessions for clean test state
        session.query(ActiveSession).delete()
        session.commit()

    # Trigger login 4 times
    payload = LoginRequest(email="admin@arandu.com.br", password="Aranduadmin")
    
    tokens = []
    for i in range(4):
        response = login(payload)
        tokens.append(response["access_token"])
        print(f"Login {i+1} succeeded.")

    # Check active sessions in the database
    with get_db_session() as session:
        active_sessions = session.query(ActiveSession).order_by(ActiveSession.created_at.asc()).all()
        print(f"\nNumber of active sessions: {len(active_sessions)}")
        
        # We expect exactly 3 sessions
        assert len(active_sessions) == 3, f"Expected 3 sessions, got {len(active_sessions)}"
        
        # We expect the first token to be kicked out (not in the database)
        first_token_active = session.query(ActiveSession).filter(ActiveSession.token == tokens[0]).first()
        assert first_token_active is None, "Expected the first token to be kicked out, but it is still active!"
        print("Success: First token was successfully kicked out!")
        
        # We expect tokens 1, 2, and 3 to be active
        for i in range(1, 4):
            token_active = session.query(ActiveSession).filter(ActiveSession.token == tokens[i]).first()
            assert token_active is not None, f"Expected token {i} to be active, but it was not found!"
        print("Success: Tokens 2, 3, and 4 are active.")

    print("\nAll checks passed successfully!")

if __name__ == "__main__":
    run_test()
