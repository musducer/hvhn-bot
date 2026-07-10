import inspect
import unittest
import cogs.ai as ai


class KnowledgeRecallTest(unittest.TestCase):
    def test_knowledge_context_uses_expansion(self):
        src = inspect.getsource(ai.AI._knowledge_context)
        self.assertIn("expand_query_terms", src)


if __name__ == "__main__":
    unittest.main()
