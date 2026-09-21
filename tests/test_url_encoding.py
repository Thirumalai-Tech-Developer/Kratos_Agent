import unittest
from kratos_agent.utils.shell_quote import youtube_search_url, build_url

class TestUrlEncoding(unittest.TestCase):
    def test_youtube_search_url(self):
        url = youtube_search_url("God of War")
        self.assertEqual(url, "https://www.youtube.com/results?search_query=God+of+War")
        self.assertNotIn(" ", url)

    def test_youtube_search_url_special_chars(self):
        # Must encode apostrophe, ampersand, quotes, and non-ASCII
        url = youtube_search_url("god's war & peace \"100%\" காட்")
        self.assertNotIn(" ", url)
        self.assertNotIn("'", url)
        self.assertNotIn('"', url)
        self.assertNotIn("& ", url)
        # Verify query part has no raw spaces or unencoded ampersands
        query_part = url.split("?search_query=")[1]
        self.assertNotIn("&", query_part)

    def test_build_url(self):
        url = build_url(
            scheme="https",
            netloc="www.youtube.com",
            path="/results",
            query={"search_query": "God of War & Ragnarok"},
        )
        self.assertEqual(url, "https://www.youtube.com/results?search_query=God+of+War+%26+Ragnarok")
        self.assertNotIn(" ", url)

if __name__ == "__main__":
    unittest.main()
