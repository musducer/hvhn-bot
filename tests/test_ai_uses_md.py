import inspect
import unittest
import cogs.ai as ai


class AiUsesMdTest(unittest.TestCase):
    def test_pdf_retrieval_calls_md(self):
        src = inspect.getsource(ai.AI._pdf_retrieval)
        self.assertIn("retrieve_md_knowledge", src)

    def test_module_imports_md(self):
        self.assertTrue(hasattr(ai, "retrieve_md_knowledge"))


if __name__ == "__main__":
    unittest.main()
