import os
import unittest

from paperwatch.clients.openai_compatible import OpenAICompatibleClient


class OpenAICompatibleClientTest(unittest.TestCase):
    def test_explicit_api_key_takes_precedence(self):
        os.environ["PAPERWATCH_TEST_KEY"] = "env-key"
        client = OpenAICompatibleClient(
            api_key_env="PAPERWATCH_TEST_KEY",
            base_url="https://example.com/v1",
            timeout_seconds=1,
            api_key="file-key",
        )
        self.assertEqual(client.api_key, "file-key")

    def test_env_key_is_used_when_file_key_empty(self):
        os.environ["PAPERWATCH_TEST_KEY"] = "env-key"
        client = OpenAICompatibleClient(
            api_key_env="PAPERWATCH_TEST_KEY",
            base_url="https://example.com/v1",
            timeout_seconds=1,
            api_key="",
        )
        self.assertEqual(client.api_key, "env-key")


if __name__ == "__main__":
    unittest.main()
