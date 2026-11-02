import sys
import textwrap
import unittest

from . import HOME
from amadeus_core import agent, mcp, playbooks, tools

ECHO = textwrap.dedent('''
    import json, sys
    for line in sys.stdin:
        m = json.loads(line)
        if "id" not in m:
            continue
        if m["method"] == "initialize":
            r = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "echo", "version": "1"}}
        elif m["method"] == "tools/list":
            r = {"tools": [{"name": "echo", "description": "Echo text", "inputSchema": {"type": "object",
                 "properties": {"text": {"type": "string"}}}}]}
        else:
            r = {"content": [{"type": "text", "text": "echo: " + m["params"]["arguments"].get("text", "")}]}
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}), flush=True)
''')


class OwnSkills(unittest.TestCase):
    def test_write_load_and_remove_your_own_skill(self):
        name = agent.skill_add("Meeting Notes", "Sort meeting notes", "meeting, minutes", "Sort into decisions and to-dos.")
        s = agent.skills()[name]
        self.assertEqual(name, "meeting-notes")
        self.assertEqual(s["triggers"], ["meeting", "minutes"])
        self.assertIn("decisions", s["body"])
        self.assertTrue(agent.own_skill(name))
        agent.skill_remove(name)
        self.assertNotIn(name, agent.skills())

    def test_a_skill_md_file_and_built_in_skills_stay(self):
        name = agent.skill_add(file="---\nname: haiku\ndescription: Write haiku.\n---\nThree lines, 5-7-5.\n")
        self.assertEqual(agent.skills()[name]["body"].strip(), "Three lines, 5-7-5.")
        agent.skill_remove(name)
        with self.assertRaises(ValueError):
            agent.skill_remove("calendar")
        with self.assertRaises(ValueError):
            agent.skill_add("calendar", "x", "", "y")


class OwnPlaybooks(unittest.TestCase):
    def test_add_match_and_remove(self):
        playbooks.own_add("Friday wrap-up", "wrap up the week, friday wrap-up", "1. Open to-dos\n2. Next week")
        p = playbooks.own_match("Can you wrap up the week?")
        self.assertEqual(p["title"], "Friday wrap-up")
        self.assertEqual(playbooks.own_match("Run playbook: Friday wrap-up")["id"], p["id"])
        self.assertIsNone(playbooks.match("Run playbook: Friday wrap-up"))
        self.assertTrue(any(x.get("own") for x in playbooks.listing()))
        playbooks.own_remove(p["id"])
        self.assertIsNone(playbooks.own_match("wrap up the week"))


class OwnConnectors(unittest.TestCase):
    def test_an_mcp_server_becomes_tools_that_need_approval(self):
        path = HOME + "/echo_mcp.py"
        with open(path, "w") as f:
            f.write(ECHO)
        self.assertEqual(mcp.add("Echo", f"{sys.executable} {path}")["tools"], ["echo"])
        try:
            t = tools.get_tool("mcp_echo_echo")
            self.assertTrue(t["approval"])
            self.assertIn("echo: hi", t["fn"](text="hi"))
            self.assertIn("not instructions", t["fn"](text="hi"))
        finally:
            mcp.remove("Echo")
        self.assertIsNone(tools.get_tool("mcp_echo_echo"))

    def test_a_command_that_is_no_mcp_server_is_refused(self):
        with self.assertRaises(ValueError):
            mcp.add("Bad", f"{sys.executable} -c 'import sys; sys.exit(1)'")


if __name__ == "__main__":
    unittest.main()
