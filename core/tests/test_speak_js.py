"""web/speak.js, run in Node with a stand-in for the browser: the spoken lines of one answer are all said, in order,
each once. (An answer that looks something up has a short line before ("I'll check the weather") and the real one
after; the real one used to be dropped, so you only heard that it would look.)"""
import os
import shutil
import subprocess
import unittest

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
SCRIPT = r"""
const said = [];
globalThis.window = globalThis;
globalThis.fetch = async (url, o) => { said.push(JSON.parse(o.body).text); return { ok: true, blob: async () => "b" }; };
globalThis.URL = { createObjectURL: () => "u", revokeObjectURL: () => {} };
globalThis.Audio = class { constructor() { setTimeout(() => this.onended && this.onended(), 1); } play() { return Promise.resolve(); } pause() {} };
require(process.argv[1]);
let busy = true;
const A = makeAloud({ busy: () => busy, talk() {}, speaking() {}, idle() {}, failed(e) { console.error(e); }, strip: (t) => t });
A.start();
A.own("I'll check the weather for both places.");
A.feed("Let me search for the forecast.", false);          // the text of the answer: never read once a line was said
A.own("I'll check the weather for both places.");          // the same line again (a retry): said once
A.own("Winterthur: sunny, 7 degrees, low of minus 3. Wallisellen: sunny, 7 degrees, low of minus 2.");
A.feed("Let me search ... **Winterthur**: sunny ...", true);
busy = false;
setTimeout(() => console.log(JSON.stringify(said)), 200);
"""


@unittest.skipUnless(shutil.which("node"), "needs Node")
class SpokenLines(unittest.TestCase):
    def test_every_spoken_line_of_an_answer_is_said_once(self):
        out = subprocess.run(["node", "-e", SCRIPT, os.path.join(WEB, "speak.js")], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        import json
        self.assertEqual(json.loads(out.stdout), ["I'll check the weather for both places.",
                                                  "Winterthur: sunny, 7 degrees, low of minus 3. Wallisellen: sunny, 7 degrees, low of minus 2."])


if __name__ == "__main__":
    unittest.main()
