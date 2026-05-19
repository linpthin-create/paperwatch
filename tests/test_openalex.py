import unittest

from paperwatch.sources.openalex import _inverted_index_to_text, _parse_work


class OpenAlexSourceTest(unittest.TestCase):
    def test_inverted_index_to_text(self):
        self.assertEqual(
            _inverted_index_to_text({"hello": [0], "world": [1]}),
            "hello world",
        )

    def test_parse_work(self):
        paper = _parse_work(
            {
                "id": "https://openalex.org/W123",
                "title": "A Test Paper",
                "publication_date": "2026-05-18",
                "abstract_inverted_index": {"A": [0], "test": [1], "abstract": [2]},
                "authorships": [{"author": {"display_name": "A. Researcher"}}],
                "concepts": [{"display_name": "Computer vision"}],
                "primary_location": {
                    "pdf_url": "https://example.test/paper.pdf",
                    "source": {"display_name": "Test Venue"},
                },
                "doi": "https://doi.org/10.0000/test",
            }
        )
        self.assertEqual(paper.source, "openalex")
        self.assertEqual(paper.paper_id, "W123")
        self.assertEqual(paper.abstract, "A test abstract")
        self.assertEqual(paper.venue, "Test Venue")


if __name__ == "__main__":
    unittest.main()
