from datetime import datetime, timezone
import unittest

from paperwatch.models import EmbeddingConfig, Interest, Paper, ScoredPaper
from paperwatch.rankers.embedding import rerank_by_embedding


class FakeEmbeddingClient:
    available = True

    def embeddings(self, model, inputs):
        vectors = []
        for text in inputs:
            low = text.lower()
            vectors.append([
                1.0 if "image" in low else 0.0,
                1.0 if "video" in low else 0.0,
                1.0 if "diffusion" in low else 0.0,
            ])
        return vectors


class EmbeddingRankerTest(unittest.TestCase):
    def test_embedding_rerank_adds_semantic_score(self):
        paper = Paper(
            source="arxiv",
            paper_id="2601.00001",
            title="Video Generation with Diffusion Models",
            authors=["A. Researcher"],
            abstract="We generate video from text.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=None,
            url="https://arxiv.org/abs/2601.00001",
            categories=["cs.CV"],
        )
        scored = ScoredPaper(paper, "Video Generation", 3.0, ["video generation"], [])
        grouped = {"Video Generation": [scored]}
        interests = [Interest(name="Video Generation", description="video diffusion generation")]

        reranked = rerank_by_embedding(
            grouped,
            interests,
            EmbeddingConfig(model="fake"),
            candidate_limit=10,
            client=FakeEmbeddingClient(),
        )
        self.assertIsNotNone(reranked["Video Generation"][0].semantic_score)
        self.assertGreater(reranked["Video Generation"][0].score, 3.0)


if __name__ == "__main__":
    unittest.main()
