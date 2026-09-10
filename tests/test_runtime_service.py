import unittest
from types import SimpleNamespace

from services.runtime_service import configure_server


class RuntimeServiceConfigTests(unittest.TestCase):
    def test_selects_server_and_its_scraping_cards(self):
        config = SimpleNamespace(
            KOMGA_SERVERS=[
                {"id": "one", "base_url": "http://one", "email": "a", "password": "b", "api_key": ""},
                {"id": "two", "base_url": "http://two", "email": "", "password": "", "api_key": "key"},
            ],
            KOMGA_LIBRARY_LIST=[
                {"LIBRARY": "lib-one", "SERVER_ID": "one"},
                {"LIBRARY": "lib-two", "SERVER_ID": "two"},
            ],
        )

        configure_server(config, "two")

        self.assertEqual(config.KOMGA_BASE_URL, "http://two")
        self.assertEqual(config.KOMGA_API_KEY, "key")
        self.assertEqual(config.KOMGA_LIBRARY_LIST, [{"LIBRARY": "lib-two", "SERVER_ID": "two"}])


if __name__ == "__main__":
    unittest.main()
