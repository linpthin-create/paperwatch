import unittest
import xml.etree.ElementTree as ET

from paperwatch.models import ArxivConfig
from paperwatch.sources.arxiv_oai import ArxivOaiSource


class ArxivOaiTest(unittest.TestCase):
    def test_parse_oai_record(self):
        payload = b'''<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <ListRecords>
    <record>
      <header>
        <identifier>oai:arXiv.org:2605.12345</identifier>
        <datestamp>2026-05-19</datestamp>
      </header>
      <metadata>
        <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
          <id>2605.12345</id>
          <created>2026-05-19</created>
          <authors>
            <author><forenames>Alice</forenames><keyname>Smith</keyname></author>
          </authors>
          <title>A Test Paper</title>
          <categories>cs.CV cs.AI</categories>
          <doi>10.1234/test</doi>
          <abstract> A test abstract. </abstract>
        </arXiv>
      </metadata>
    </record>
  </ListRecords>
</OAI-PMH>'''
        source = ArxivOaiSource(ArxivConfig())

        papers = source._parse_records(ET.fromstring(payload))

        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper.source, "arxiv")
        self.assertEqual(paper.paper_id, "2605.12345")
        self.assertEqual(paper.title, "A Test Paper")
        self.assertEqual(paper.authors, ["Alice Smith"])
        self.assertEqual(paper.categories, ["cs.CV", "cs.AI"])
        self.assertEqual(paper.doi, "10.1234/test")
        self.assertEqual(paper.url, "https://arxiv.org/abs/2605.12345")


if __name__ == "__main__":
    unittest.main()
