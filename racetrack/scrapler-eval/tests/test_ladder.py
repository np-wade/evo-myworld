import unittest
from scrapler_eval.ladder import load_ladder, load_config, read_fixture_html
from scrapler_eval.interface import Tier


class TestLadder(unittest.TestCase):
    def test_loads_all_tasks(self):
        tasks = load_ladder()
        self.assertEqual(len(tasks), 4)
        self.assertEqual({t.id for t in tasks},
                         {"t0-article", "t1-product", "t2-lazyfeed", "x-product-fields"})

    def test_tiers_parsed_to_enum(self):
        tasks = {t.id: t for t in load_ladder()}
        self.assertEqual(tasks["t0-article"].tier, Tier.STATIC)
        self.assertEqual(tasks["t2-lazyfeed"].tier, Tier.LAZY)

    def test_file_urls_resolved_absolute(self):
        t = next(t for t in load_ladder() if t.id == "t0-article")
        self.assertTrue(t.url.startswith("file://"))
        self.assertIn("/fixtures/pages/tier0_article.html", t.url)

    def test_answer_keys_present(self):
        t = next(t for t in load_ladder() if t.id == "t0-article")
        self.assertIn("The Marathon Continues", t.answer_key["must_contain"])

    def test_extractor_task_has_schema(self):
        t = next(t for t in load_ladder() if t.id == "x-product-fields")
        self.assertEqual(t.schema["fields"], ["name", "price", "description"])
        self.assertEqual(t.answer_key["fields"]["name"], "Anti-Detect Browser Pro")

    def test_config_weights(self):
        cfg = load_config()
        self.assertAlmostEqual(cfg["weights"]["default"]["w1"], 0.45)
        self.assertIn("latency_ms", cfg["field_stats"])

    def test_read_fixture_html(self):
        t = next(t for t in load_ladder() if t.id == "t0-article")
        html = read_fixture_html(t)
        self.assertIn("Marathon", html)
        self.assertGreater(len(html), 400)


if __name__ == "__main__":
    unittest.main()
