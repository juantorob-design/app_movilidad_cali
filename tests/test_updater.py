import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

import updater


class TestUpdaterDownloadUrls(unittest.TestCase):
    def test_allows_drive_and_github_https_hosts(self):
        for url in (
            "https://drive.google.com/uc?export=download&id=file-id",
            "https://github.com/org/repo/releases/download/v1/app.exe",
            "https://objects.githubusercontent.com/release-asset",
            "https://release-assets.githubusercontent.com/release-asset",
        ):
            with self.subTest(url=url):
                self.assertIn(updater.urlparse(url).hostname, updater.DOWNLOAD_HOSTS)

    def test_rejects_untrusted_download_host(self):
        self.assertNotIn(
            updater.urlparse("https://example.com/setup.exe").hostname,
            updater.DOWNLOAD_HOSTS,
        )

    def test_parses_large_drive_download_confirmation_form(self):
        response = Mock()
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.url = "https://drive.google.com/uc?export=download&id=file-id"
        response.text = """
            <html><body><form action="https://drive.usercontent.google.com/download">
            <input type="hidden" name="id" value="file-id">
            <input type="hidden" name="export" value="download">
            <input type="hidden" name="confirm" value="t">
            <input type="hidden" name="uuid" value="temporary-token">
            </form></body></html>
        """

        confirmation_url = updater._drive_confirmation_url(response)

        self.assertEqual(
            urlparse(confirmation_url).hostname,
            "drive.usercontent.google.com",
        )
        self.assertEqual(
            parse_qs(urlparse(confirmation_url).query),
            {
                "id": ["file-id"],
                "export": ["download"],
                "confirm": ["t"],
                "uuid": ["temporary-token"],
            },
        )

    def test_does_not_accept_confirmation_forms_from_untrusted_hosts(self):
        response = Mock()
        response.headers = {"Content-Type": "text/html"}
        response.url = "https://drive.google.com/uc?export=download&id=file-id"
        response.text = """
            <form action="https://example.com/download">
            <input name="id" value="file-id">
            <input name="export" value="download">
            <input name="confirm" value="t">
            </form>
        """

        self.assertEqual(updater._drive_confirmation_url(response), "")

    def test_does_not_process_html_from_non_drive_hosts(self):
        response = Mock()
        response.headers = {"Content-Type": "text/html"}
        response.url = "https://github.com/org/repo/releases/download/v1/app.exe"
        response.text = '<form action="https://drive.usercontent.google.com/download"></form>'

        self.assertEqual(updater._drive_confirmation_url(response), "")


if __name__ == "__main__":
    unittest.main()
