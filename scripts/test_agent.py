import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from contextlib import contextmanager
from datetime import datetime

# Add parent folder (project root) to sys.path to allow standalone execution
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent import agent_settings, LocalFilter, calculate_local_heuristic_score, AgentOrchestrator
from database.models import Base, News, Source, SendStatus

# Create in-memory SQLite database for testing
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)

@contextmanager
def mock_get_db_session():
    session = TestingSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

curador_orch_mod = sys.modules["agent.Curador de Notícias.orchestrator"]

class TestCurationAgent(unittest.TestCase):
    
    def setUp(self):
        # Clear tables before each test
        with mock_get_db_session() as session:
            session.query(News).delete()
            session.query(Source).delete()
            session.commit()

    def test_heuristic_scoring(self):
        """Test keyword-based local heuristic scoring."""
        # High tech/AI title should score well
        score_tech = calculate_local_heuristic_score("Nova Inteligência Artificial da OpenAI revoluciona processamento de LLM")
        # In this case: inteligência (+3), artificial (+3), openai (+3), llm (+3), but has hype word 'revoluciona' (-3). Total: 5 + 3 + 3 + 3 + 3 - 3 = 14, but wait! The code matches 4 keywords which is capped at 3: 5 + 3 - 2 = 6.
        self.assertEqual(score_tech, 6)
        
        # Clickbait/hype title should be penalized
        score_hype = calculate_local_heuristic_score("Você não vai acreditar no segredo bombástico revelado por esta empresa")
        self.assertLess(score_hype, 5)
        
        # Generic irrelevant title
        score_generic = calculate_local_heuristic_score("Receita de bolo de cenoura com cobertura de chocolate deliciosa")
        self.assertEqual(score_generic, 5)

    def test_local_filtering(self):
        """Test length checking, blacklisting, and in-memory deduplication."""
        news_list = [
            # Short title (filtered)
            {"id": 1, "original_title": "Short", "source_name": "Tech"},
            # Blacklisted keyword 'fofoca' (filtered)
            {"id": 2, "original_title": "Fofoca quente sobre celebridades na TV ontem à noite", "source_name": "Tech"},
            # Valid item 1
            {"id": 3, "original_title": "Nvidia anuncia novos chips de silício para IA generativa", "source_name": "TechCrunch"},
            # Valid item 2 (exact duplicate of 1, should be filtered)
            {"id": 4, "original_title": "Nvidia anuncia novos chips de silício para IA generativa", "source_name": "TechCrunch"},
            # Valid item 3 (similar title, should be filtered by 0.8 similarity threshold)
            {"id": 5, "original_title": "Nvidia anuncia chips de silício para IA generativas", "source_name": "Wired"}
        ]
        
        filtered = LocalFilter.filter_and_deduplicate(news_list, recent_titles=[])
        
        # Only item 3 should remain
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["id"], 3)

    @patch.object(curador_orch_mod, "GeminiGateway")
    @patch.object(curador_orch_mod, "get_db_session", new=mock_get_db_session)
    def test_orchestrator_pipeline(self, mock_gateway_cls):
        """Test full orchestration with in-memory SQLite and mocked gateway."""
        # Setup mock gateway
        mock_gateway = MagicMock()
        mock_gateway_cls.return_value = mock_gateway
        
        # Mock Phase 1 response and Phase 2 response
        mock_gateway.call_structured_api.side_effect = [
            # Phase 1 response
            {
                "classifications": [
                    {"id": 1, "score": 9},
                    {"id": 2, "score": 8},
                    {"id": 3, "score": 4}
                ]
            },
            # Phase 2 response
            {
                "items": [
                    {
                        "id": 1,
                        "score_relevance": 95,
                        "justification": "AI breakthrough",
                        "category": "IA/Automação",
                        "priority": "Alta"
                    },
                    {
                        "id": 2,
                        "score_relevance": 82,
                        "justification": "Important hardware update",
                        "category": "Tecnologia",
                        "priority": "Média"
                    }
                ]
            }
        ]
        
        # Seed Source and News in database
        with mock_get_db_session() as session:
            source = Source(id=1, name="TechCrunch", rss_url="http://techcrunch.com/rss", type="Internacional")
            session.add(source)
            session.commit()
            
            news1 = News(
                id=1, 
                source_id=1, 
                original_title="OpenAI releases GPT-5 with reasoning capabilities", 
                link="http://news1.com",
                hash_title="hash1",
                is_curated=False,
                send_status=SendStatus.PENDENTE
            )
            news2 = News(
                id=2, 
                source_id=1, 
                original_title="Nvidia launches Blackwell chips worldwide", 
                link="http://news2.com",
                hash_title="hash2",
                is_curated=False,
                send_status=SendStatus.PENDENTE
            )
            news3 = News(
                id=3, 
                source_id=1, 
                original_title="Local town council holds minor meeting about parking lots", 
                link="http://news3.com",
                hash_title="hash3",
                is_curated=False,
                send_status=SendStatus.PENDENTE
            )
            session.add_all([news1, news2, news3])
            session.commit()
            
        # Override settings values for testing the top news curation rules
        agent_settings.FINAL_MIN_NEWS = 1
        agent_settings.FINAL_MAX_NEWS = 2
        agent_settings.EXCEPTIONAL_SCORE_THRESHOLD = 90
        agent_settings.PHASE1_BATCH_SIZE = 20
        agent_settings.TOP_N_SELECTION = 50
        
        # Run orchestrator
        orchestrator = AgentOrchestrator()
        report = orchestrator.run_curation_pipeline()
        
        # Verify output report metrics
        self.assertIn("API Calls made: 2", report)
        self.assertIn("News detailed in Phase 2: 2", report)
        
        # Fetch from database and verify state
        with mock_get_db_session() as session:
            db_news1 = session.query(News).filter(News.id == 1).first()
            db_news2 = session.query(News).filter(News.id == 2).first()
            db_news3 = session.query(News).filter(News.id == 3).first()
            
            # Verify news1 is curated, relevance is 95, priority is Alta, and send_status is PENDENTE (selected)
            self.assertTrue(db_news1.is_curated)
            self.assertEqual(db_news1.relevance_score, 95)
            self.assertEqual(db_news1.category, "IA/Automação")
            self.assertEqual(db_news1.send_status, SendStatus.PENDENTE)
            
            # Verify news2 is curated, relevance is 82, priority is Média, but send_status is FALHA (exceeds min selection and score is < 90)
            self.assertTrue(db_news2.is_curated)
            self.assertEqual(db_news2.relevance_score, 82)
            self.assertEqual(db_news2.send_status, SendStatus.FALHA)
            
            # Verify news3 is curated (from remaining Phase 1 step) with relevance 40 (scaled from 4)
            self.assertTrue(db_news3.is_curated)
            self.assertEqual(db_news3.relevance_score, 40)
            self.assertEqual(db_news3.send_status, SendStatus.FALHA)

if __name__ == "__main__":
    unittest.main()
