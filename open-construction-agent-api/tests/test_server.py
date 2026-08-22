import unittest

from openconstruction_mcp.server import TOOLS, handle_request


class ServerTest(unittest.TestCase):
    def test_lists_tools(self):
        result = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = [tool["name"] for tool in result["result"]["tools"]]
        self.assertIn("search_resources", names)
        self.assertIn("find_datasets", names)
        self.assertIn("run_dataset_discovery", names)
        self.assertIn("validate_metadata_record", names)
        self.assertIn("list_skills", names)
        self.assertIn("get_skill", names)
        self.assertIn("get_dataset_download_plan", names)
        self.assertIn("download_dataset", names)
        self.assertIn("get_download_status", names)
        self.assertIn("cancel_download", names)
        self.assertEqual(len(names), len({tool["name"] for tool in TOOLS}))

    def test_remote_tool_list_excludes_local_filesystem_tools(self):
        result = handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            allow_download_execution=False,
        )
        names = [tool["name"] for tool in result["result"]["tools"]]
        self.assertIn("get_dataset_download_plan", names)
        self.assertNotIn("download_dataset", names)
        self.assertNotIn("get_download_status", names)
        self.assertNotIn("cancel_download", names)

    def test_initialize(self):
        result = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(result["result"]["serverInfo"]["name"], "openconstruction")
        self.assertIn("auth_required", result["result"]["instructions"])
        self.assertIn("never ask for credentials", result["result"]["instructions"])
        self.assertIn("tools", result["result"]["capabilities"])


if __name__ == "__main__":
    unittest.main()
