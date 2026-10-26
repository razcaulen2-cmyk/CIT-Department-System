import unittest
from pathlib import Path

from app_factory import create_app


class OfflineAssetTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_layouts_do_not_depend_on_external_assets(self):
        template_root = Path(__file__).resolve().parents[1] / "templates" / "layout"
        for template_name in ("admin_base.html", "public_base.html", "student_base.html"):
            with self.subTest(template=template_name):
                content = (template_root / template_name).read_text(encoding="utf-8")
                self.assertNotIn("https://", content)
                self.assertNotIn("http://", content)
                self.assertIn("vendor/bootstrap/bootstrap.min.css", content)

    def test_required_vendor_assets_are_served_locally(self):
        asset_paths = (
            "/static/vendor/bootstrap/bootstrap.min.css",
            "/static/vendor/bootstrap/bootstrap.bundle.min.js",
            "/static/vendor/bootstrap-icons/bootstrap-icons.min.css",
            "/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2",
            "/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff",
            "/static/vendor/chart.js/chart.umd.min.js",
        )
        for asset_path in asset_paths:
            with self.subTest(asset=asset_path):
                response = self.client.get(asset_path)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.data)
                response.close()


if __name__ == "__main__":
    unittest.main()
