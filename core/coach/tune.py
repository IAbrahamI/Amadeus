#!/usr/bin/env python3
"""Coaching: find the texts (a "pack", see pack.py) with which a small local model picks the right tool most often.

A big model is the coach. It never runs inside Amadeus and never sees real chats or mail: it reads the report of what
the small model got wrong on the made-up cases (cases.py), rewrites the texts, and this script scores the new version
on the small model. A version is kept only if it beats the one before. No model weights change.

One round, from core/ (needs Ollama with the model; a throw-away home folder, so nothing of yours is read or changed):

  python3 coach/tune.py check                                    the cases and packs are sound (no model needed)
  python3 coach/tune.py baseline out/base.json                   the texts as the code has them, as a pack to edit
  python3 coach/tune.py score MODEL --out out/a.json             score the code's texts (all cases, 2 rounds)
  python3 coach/tune.py report out/a.json > out/a.md             what went wrong, with the texts involved: for the coach
     ... the coach writes out/try1.json (only the texts it changes) ...
  python3 coach/tune.py score MODEL --pack out/try1.json --out out/b.json
  python3 coach/tune.py compare out/a.json out/b.json            better on the cases it was tuned on, not worse on the held-back ones?

The coach only ever gets the report of the cases it tunes on (train). The held-back third is scored but never shown,
so a pack that only learned the test by heart is found out."""
import argparse
import importlib.util
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.dirname(HERE)
ROUNDS = 2
MORE_CHARS = 1.10  # a better pack may make each request at most this much bigger


def _replay(model):
    """tests/live_replay.py sets up the throw-away home, counts what each request costs and runs one case; it is loaded
    as the script it is (it reads the model from the command line)."""
    argv, sys.argv = sys.argv, ["live_replay.py", model]
    try:
        spec = importlib.util.spec_from_file_location("live_replay", os.path.join(CORE, "tests", "live_replay.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.argv = argv
    return mod


def _stand_ins(tools):
    """Every area is offered, and nothing reaches outside the test: no web, no programs opened, no long-term memory."""
    tools.missing = lambda connector: ""
    canned = {
        "web_search": lambda **k: "<<<WEB DATA\n1. A made-up result - https://example.org/result\nMade-up text for this test: 14 degrees, light rain.\nWEB DATA>>>",
        "web_read": lambda **k: "<<<WEB DATA\nhttps://example.org/guide\nA made-up page for this test. It explains three steps.\nWEB DATA>>>",
        "open_app": lambda **k: "Opened.", "open_page": lambda **k: "Opened.",
        "remember": lambda **k: "Saved.", "recall": lambda **k: "No relevant memories.",
        "memory_overview": lambda **k: "- Likes hiking.\n- Works as a nurse.",
        "work_status": lambda **k: "No work runs yet.",
    }
    for name, fn in canned.items():
        if name in tools.BY_NAME:
            tools.BY_NAME[name]["fn"] = fn
    import datetime
    day = datetime.date.today() + datetime.timedelta(days=3)
    try:  # one event to move or cancel
        tools.BY_NAME["calendar_add"]["fn"](title="Dentist", start=f"{day} 15:00", end=f"{day} 16:00")
    except Exception as e:
        print("no calendar event for the test:", str(e)[:100], flush=True)


def score(model, pack_file, which, rounds, only, out):
    from coach import cases, pack
    R = _replay(model)
    from amadeus_core import grounding, tools
    _stand_ins(tools)
    base = pack.current()
    p = pack.load(pack_file) if pack_file else {}
    bad = pack.problems(p, base)
    if bad:
        sys.exit("This pack can't be used: " + "; ".join(bad))
    pack.apply(p)
    todo = [(x["id"], x) for x in cases.split(which)]
    if which != "held":  # the failures seen in real chats (tests/live_replay.py) are tuned on too
        todo += [("replay: " + name, {"hist": hist, "text": text, "speak": speak, "ok": ok, "lang": name[-3:-1], "want": "(see tests/live_replay.py)"})
                 for name, hist, text, speak, ok in R.CASES]
    todo = [(i, x) for i, x in todo if not only or only.lower() in i.lower()]
    result = {"model": model, "pack": pack_file or "", "split": which, "rounds": rounds, "cases": {}}
    start, t0 = dict(R.COST), time.time()
    for n, (cid, case) in enumerate(todo, 1):
        entry = {"right": 0, "of": rounds, "held": cid in {x["id"] for x in cases.CASES} and cases.held(cid), "fake": 0,
                 "lang": case["lang"], "text": case["text"], "want": case["want"], "fails": []}
        for _ in range(rounds):
            calls, shown, said = R.run(case["hist"], case["text"], case["speak"])
            fake = not any(c.startswith("approved:") or (tools.BY_NAME.get(c) or {}).get("approval") for c, _ in calls) and bool(grounding.unbacked(shown))
            if "ok" in case:
                good, why = bool(case["ok"](calls, shown, said)), "see its check in tests/live_replay.py"
            else:
                good, why = cases.check(case, calls, shown, tools, grounding)
            entry["right"] += good
            entry["fake"] += fake
            if not good:
                entry["fails"].append({"why": why, "calls": [[c, a] for c, a in calls][:6], "shown": shown[:300], "said": said[:120]})
        result["cases"][cid] = entry
        print(f"{n:3d}/{len(todo)} {entry['right']}/{rounds} {'held ' if entry['held'] else '     '}{cid}", flush=True)
    made = R.COST["calls"] - start["calls"]
    result.update(calls=made, chars_per_call=(R.COST["chars"] - start["chars"]) // max(made, 1),
                  tokens_read_per_call=(R.COST["read"] - start["read"]) // max(made, 1), seconds=int(time.time() - t0))
    print(summary(result))
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
    return result


def totals(result, held=None):
    """(right, of, fake) over all cases, or only the held-back / tuned-on ones."""
    rows = [c for c in result["cases"].values() if held is None or c["held"] == held]
    return sum(c["right"] for c in rows), sum(c["of"] for c in rows), sum(c["fake"] for c in rows)


def summary(result):
    (r, n, f), (tr, tn, _), (hr, hn, _) = totals(result), totals(result, False), totals(result, True)
    return (f"\n{result['model']}{' with ' + result['pack'] if result['pack'] else ''}: {r}/{n} right ({tr}/{tn} tuned on, {hr}/{hn} held back), "
            f"{f} made-up \"done\". {result['calls']} model calls, {result['chars_per_call']:,} chars sent per call, "
            f"{result['tokens_read_per_call']:,} tokens read per call, {result['seconds']}s")


def verdict(a, b):
    """(keep b?, the reasons). b is kept when it is clearly better where it was tuned and no worse anywhere else."""
    (atr, atn, _), (btr, btn, _) = totals(a, False), totals(b, False)
    (ahr, ahn, _), (bhr, bhn, _) = totals(a, True), totals(b, True)
    af, bf = totals(a)[2], totals(b)[2]
    why = [f"tuned on: {atr}/{atn} -> {btr}/{btn}", f"held back: {ahr}/{ahn} -> {bhr}/{bhn}", f"made-up \"done\": {af} -> {bf}",
           f"chars per call: {a['chars_per_call']:,} -> {b['chars_per_call']:,}"]
    if (atn, ahn) != (btn, bhn):
        return False, why + ["the two runs did not score the same cases: run both the same way"]
    keep = btr >= atr + 2 and bhr >= ahr and bf <= af and b["chars_per_call"] <= a["chars_per_call"] * MORE_CHARS
    if btr < atr + 2:
        why.append("not clearly better where it was tuned (two more right answers are the least that counts: one can be chance)")
    if bhr < ahr:
        why.append("worse on the held-back cases: it fits the test, not the task")
    if bf > af:
        why.append("more made-up \"done\"")
    if b["chars_per_call"] > a["chars_per_call"] * MORE_CHARS:
        why.append("each request got more than 10% bigger")
    return keep, why


def report(result, pack_file):
    """What the coach reads: only the cases it may tune on, what was asked, what the model did, and the texts involved."""
    from coach import pack
    from amadeus_core import tools
    p = pack.load(pack_file) if pack_file else {}
    texts = pack.current()
    texts.update({k: p[k] for k in pack.TEXTS if p.get(k)})
    descriptions = {**texts["tools"], **(p.get("tools") or {})}
    texts["area_words"] = {**texts["area_words"], **(p.get("area_words") or {})}
    tr, tn, _ = totals(result, False)
    out = [f"# What {result['model']} got wrong ({tr}/{tn} right on the cases to tune on)", "",
           "Rewrite the texts so that these come out right without breaking the ones that already work. Keep them short:",
           "every character is read on every request. Change as little as fixes the pattern, not one case at a time.",
           "Return a pack (JSON) with only the keys you changed: system, pick_ask, fill_ask, small_talk_hint,",
           "tools {name: description}, area_words {area: regex alternatives}.", ""]
    involved = set()
    for cid, c in result["cases"].items():
        if c["held"] or not c["fails"]:
            continue
        out += [f"## {cid} ({c['lang']}): {c['right']}/{c['of']} right", f"- The user wrote: {c['text']!r}", f"- Right would be: {c['want']}"]
        for f in c["fails"]:
            called = ", ".join(f"{n}({json.dumps(a, ensure_ascii=False)[:120]})" for n, a in f["calls"]) or "no tool"
            out += [f"- It did: {called}", f"  - wrong because: {f['why']}", f"  - it answered: {f['shown'][:200]!r}"]
            involved |= {n.removeprefix("approved:") for n, _ in f["calls"]}
        involved |= {w for part in str(c["want"]).replace("&", "|").split("|") for w in [part] if w in tools.BY_NAME}
        area = next((a for a, rx in tools.AREA_RE.items() if rx.search(c["text"])), "")
        out += [f"- Area picked from its words: {area or 'none (base tools only)'}", ""]
    out += ["# The texts as they are", "", "## system", "```", texts["system"], "```", "", "## pick_ask", "```", texts["pick_ask"], "```", "",
            "## fill_ask", "```", texts["fill_ask"], "```", "", "## tools involved in the failures"]
    out += [f"- **{n}**: {descriptions[n]}" for n in sorted(involved) if n in descriptions]
    out += ["", "## area_words (checked in this order; the first that fits is the area)"]
    out += [f"- **{a}**: `{w}`" for a, w in texts["area_words"].items()]
    out += ["", "## the tools of each area", f"- **always**: {', '.join(tools.BASE)}"] + [f"- **{a}**: {', '.join(n)}" for a, n in tools.AREAS.items()]
    return "\n".join(out) + "\n"


def check():
    """The cases and the packs are sound. Needs no model: also run by the unit tests."""
    from coach import cases, pack
    from amadeus_core import tools
    bad = []
    for x in cases.CASES:
        for name in [w for part in x["want"].split("&") for w in part.split("|")] + list(x["not"]):
            if name in ("none", "cant") or (name.startswith("@") and any(t["connector"] == name[1:] for t in tools.TOOLS)):
                continue
            if name not in tools.BY_NAME:
                bad.append(f"{x['id']}: no tool is called {name!r}")
    n_held = len(cases.split("held"))
    if not 0.2 <= n_held / len(cases.CASES) <= 0.4:
        bad.append(f"{n_held} of {len(cases.CASES)} cases are held back: should be about a third")
    for lang in ("en", "de", "es"):
        if not any(x["lang"] == lang for x in cases.split("held")):
            bad.append(f"no held-back case in {lang}")
    folder = os.path.join(HERE, "packs")
    for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if f.endswith(".json"):
            bad += [f"packs/{f}: {p}" for p in pack.problems(pack.load(os.path.join(folder, f)), pack.current())]
    return bad


def main():
    sys.path.insert(0, CORE)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    b = sub.add_parser("baseline")
    b.add_argument("out")
    s = sub.add_parser("score")
    s.add_argument("model")
    s.add_argument("--pack")
    s.add_argument("--split", choices=("all", "train", "held"), default="all")
    s.add_argument("--rounds", type=int, default=ROUNDS)
    s.add_argument("--only", default="")
    s.add_argument("--out")
    r = sub.add_parser("report")
    r.add_argument("result")
    r.add_argument("--pack")
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    a = ap.parse_args()
    if a.cmd == "score":
        score(a.model, a.pack, a.split, a.rounds, a.only, a.out)
        return
    if a.cmd == "compare":
        keep, why = verdict(json.load(open(a.a, encoding="utf-8")), json.load(open(a.b, encoding="utf-8")))
        print("\n".join(why))
        print("KEEP the new pack." if keep else "Do NOT keep it.")
        sys.exit(0 if keep else 1)
    import tempfile
    os.environ["HOME"] = os.environ["USERPROFILE"] = tempfile.mkdtemp(prefix="amadeus-coach-")  # never the real data folder
    if a.cmd == "check":
        bad = check()
        print("\n".join(bad) if bad else "The cases and packs are sound.")
        sys.exit(1 if bad else 0)
    if a.cmd == "baseline":
        from coach import pack
        pack.save(pack.current(), a.out)
        print("Written:", a.out)
    if a.cmd == "report":
        print(report(json.load(open(a.result, encoding="utf-8")), a.pack), end="")


if __name__ == "__main__":
    main()
