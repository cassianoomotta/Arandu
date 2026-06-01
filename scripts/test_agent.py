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
from database.models import Base, News, Source, SendStatus, NoticiasRejeitadas

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
            session.query(NoticiasRejeitadas).delete()
            session.commit()

    def test_heuristic_scoring(self):
        """Test keyword-based local heuristic scoring."""
        # High tech/AI title should score well
        score_tech = calculate_local_heuristic_score("Nova Inteligência Artificial da OpenAI revoluciona processamento de LLM")
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
        
        # Mock Curation response
        mock_gateway.call_structured_api.side_effect = [
            {
                "items": [
                    {
                        "id": 1,
                        "status": "APROVADA",
                        "justificativa": "AI breakthrough",
                        "categoria_identificada": "Inteligência Artificial",
                        "score": 5
                    },
                    {
                        "id": 2,
                        "status": "APROVADA",
                        "justificativa": "Important hardware update",
                        "categoria_identificada": "Tecnologia",
                        "score": 4
                    },
                    {
                        "id": 3,
                        "status": "REPROVADA",
                        "justificativa": "Política local sem inovação",
                        "categoria_identificada": "Outros",
                        "score": 2
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
        
        # Run orchestrator
        orchestrator = AgentOrchestrator()
        report = orchestrator.run_curation_pipeline()
        
        # Verify output report metrics
        self.assertIn("API Calls made: 1", report)
        
        # Fetch from database and verify state
        with mock_get_db_session() as session:
            db_news1 = session.query(News).filter(News.id == 1).first()
            db_news2 = session.query(News).filter(News.id == 2).first()
            db_news3 = session.query(News).filter(News.id == 3).first()
            rejected = session.query(NoticiasRejeitadas).filter(NoticiasRejeitadas.id_noticia == 3).first()
            
            # Verify news1 is curated, relevance is 5, priority is alta, and send_status is PENDENTE (selected)
            self.assertIsNotNone(db_news1)
            self.assertTrue(db_news1.is_curated)
            self.assertEqual(db_news1.relevance_score, 5)
            self.assertEqual(db_news1.category, "Inteligência Artificial")
            self.assertEqual(db_news1.priority, "alta")
            self.assertEqual(db_news1.destaque, True)
            self.assertEqual(db_news1.send_status, SendStatus.PENDENTE)
            
            # Verify news2 is curated, relevance is 4, priority is media, and is curated
            self.assertIsNotNone(db_news2)
            self.assertTrue(db_news2.is_curated)
            self.assertEqual(db_news2.relevance_score, 4)
            self.assertEqual(db_news2.priority, "media")
            
            # Verify news3 was deleted from news table and moved to noticias_rejeitadas
            self.assertIsNone(db_news3)
            self.assertIsNotNone(rejected)
            self.assertEqual(rejected.motivo_rejeicao, "Política local sem inovação")

if __name__ == "__main__":
    unittest.main()
