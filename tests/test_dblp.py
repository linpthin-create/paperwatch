import unittest

from paperwatch.sources.dblp import _parse_hit, _safe_query


class DblpSourceTest(unittest.TestCase):
    def test_parse_hit(self):
        paper = _parse_hit(
            {
                "info": {
                    "key": "conf/test/Paper26",
                    "title": "A dblp Test Paper.",
                    "authors": {"author": [{"text": "A. Researcher"}, {"text": "B. Researcher"}]},
                    "year": "2026",
                    "venue": "TEST",
                    "type": "Conference and Workshop Papers",
                    "doi": "10.0000/test",
                    "ee": "https://doi.org/10.0000/test",
                }
            }
        )
        self.assertEqual(paper.source, "dblp")
        self.assertEqual(paper.paper_id, "conf/test/Paper26")
        self.assertEqual(paper.title, "A dblp Test Paper")
        self.assertEqual(paper.authors, ["A. Researcher", "B. Researcher"])
        self.assertEqual(paper.published_at.year, 2026)

    def test_safe_query_removes_punctuation(self):
        self.assertEqual(_safe_query("single-view articulated 3D: asset_generation!"), "single view articulated 3D asset generation")


if __name__ == "__main__":
    unittest.main()
