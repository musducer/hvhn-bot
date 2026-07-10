# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

import md_embeddings
from md_embeddings import vec_literal, _parse_batch, EMBED_DIM
from md_knowledge import _rrf_merge


class VecLiteralTest(unittest.TestCase):
    def test_format(self):
        self.assertEqual(vec_literal([1, 2, 3]), "[1.000000,2.000000,3.000000]")

    def test_dim_constant(self):
        self.assertEqual(EMBED_DIM, 768)


class ParseBatchTest(unittest.TestCase):
    def test_ok(self):
        payload = {"embeddings": [{"values": [0.1, 0.2]}, {"values": [0.3, 0.4]}]}
        self.assertEqual(_parse_batch(payload), [[0.1, 0.2], [0.3, 0.4]])

    def test_missing_values_returns_none(self):
        self.assertIsNone(_parse_batch({"embeddings": [{"values": []}]}))

    def test_no_embeddings_key(self):
        self.assertIsNone(_parse_batch({"error": "quota"}))


class ProviderSelectionTest(unittest.TestCase):
    @patch.dict("os.environ", {"VOYAGE_API_KEYS": "v", "GEMINI_API_KEYS": "g"}, clear=True)
    def test_voyage_is_preferred(self):
        self.assertEqual(md_embeddings.active_provider(), "voyage")
        self.assertEqual(md_embeddings.active_dim(), 1024)

    @patch.dict("os.environ", {"HVHN_EMBED_PROVIDER": "gemini", "VOYAGE_API_KEYS": "v", "GEMINI_API_KEYS": "g"}, clear=True)
    def test_explicit_gemini(self):
        self.assertEqual(md_embeddings.active_provider(), "gemini")
        self.assertEqual(md_embeddings.active_dim(), 768)


class RrfMergeTest(unittest.TestCase):
    def _row(self, dk, idx):
        return {"doc_key": dk, "passage_index": idx, "content": f"{dk}-{idx}"}

    def test_merges_and_dedupes(self):
        a = self._row("d", 1)
        b = self._row("d", 2)
        c = self._row("d", 3)
        kw = [a, b]        # a rank1, b rank2
        vec = [b, c]       # b rank1, c rank2
        out = _rrf_merge(kw, vec, limit=3)
        keys = [(r["doc_key"], r["passage_index"]) for r in out]
        # b xuat hien ca 2 bang -> diem cao nhat, dung dau
        self.assertEqual(keys[0], ("d", 2))
        self.assertEqual(len(out), 3)
        self.assertEqual(len(set(keys)), 3)

    def test_limit_respected(self):
        rows = [self._row("d", i) for i in range(10)]
        out = _rrf_merge(rows, [], limit=4)
        self.assertEqual(len(out), 4)


if __name__ == "__main__":
    unittest.main()
