import unittest

from openconstruction_mcp.catalog import CatalogClient


def fixture(path):
    if path == "datasets.json":
        return {
            "demo-dataset": {
                "name": "Demo Safety Dataset",
                "summary": "Images for construction safety and PPE detection.",
                "data_modality": "Ground RGB",
                "classes": ["hardhat", "person"],
                "license": "Apache-2.0",
            }
        }
    if path == "models.json":
        return [
            {
                "id": "demo-model",
                "title": "Demo Safety Model",
                "abstract": "Detects PPE in construction site images.",
            }
        ]
    if path == "tools.json":
        return {
            "sections": [
                {
                    "title": "Annotation",
                    "items": [
                        {
                            "name": "Demo Label Tool",
                            "summary": "Draw bounding boxes for inspection images.",
                        }
                    ],
                }
            ]
        }
    return []


class CatalogClientTest(unittest.TestCase):
    def test_searches_category_catalogs(self):
        client = CatalogClient(fetch_json=fixture)

        datasets = client.search("hardhat safety", ["dataset"])
        self.assertEqual(datasets[0]["id"], "demo-dataset")

        models = client.search("PPE", ["model"])
        self.assertEqual(models[0]["id"], "demo-model")

        tools = client.search("bounding boxes", ["tool"])
        self.assertEqual(tools[0]["title"], "Demo Label Tool")

    def test_stats_count_resources(self):
        client = CatalogClient(fetch_json=fixture)
        stats = client.stats()
        self.assertGreaterEqual(stats["by_type"]["dataset"], 1)
        self.assertGreaterEqual(stats["by_type"]["model"], 1)


if __name__ == "__main__":
    unittest.main()
