#!/usr/bin/env python3
"""The privacy filter (Presidio) as a small program without any network: one JSON request per line on stdin, one answer per line
on stdout. macfilter.py starts it sealed off by macOS. It has no socket to listen on, and it tries one connection at start,
which has to fail: if it doesn't, Amadeus refuses to use it.
Run with: python sealed_filter.py <nlp.yaml> <probe port>"""
import json
import socket
import sys


def sealed(port):
    """It can't reach anything: not this computer's own network, not the internet."""
    for address in (("127.0.0.1", port), ("1.1.1.1", 53)):
        try:
            with socket.create_connection(address, timeout=2):
                return False
        except OSError:
            continue
    return True


def main():
    out, sys.stdout = sys.stdout, sys.stderr  # (a library printing something must not end up in an answer)
    is_sealed = sealed(int(sys.argv[2]))
    if not is_sealed:
        out.write(json.dumps({"ready": False, "sealed": False}) + "\n")
        out.flush()
        return
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import OperatorConfig, RecognizerResult
    analyzer = AnalyzerEngine(nlp_engine=NlpEngineProvider(conf_file=sys.argv[1]).create_engine(), supported_languages=["en", "de"])
    anonymizer = AnonymizerEngine()
    out.write(json.dumps({"ready": True, "sealed": True}) + "\n")
    out.flush()
    for line in sys.stdin:
        try:
            q = json.loads(line)
            if q["op"] == "analyze":
                found = analyzer.analyze(text=q["text"], language=q["language"], entities=q.get("entities"), score_threshold=q.get("score_threshold"))
                answer = [{"start": r.start, "end": r.end, "entity_type": r.entity_type, "score": r.score} for r in found]
            else:
                results = [RecognizerResult(r["entity_type"], r["start"], r["end"], r["score"]) for r in q["analyzer_results"]]
                ops = {k: OperatorConfig(v["type"], {"new_value": v["new_value"]}) for k, v in q["anonymizers"].items()}
                answer = {"text": anonymizer.anonymize(text=q["text"], analyzer_results=results, operators=ops).text}
            out.write(json.dumps({"ok": answer}) + "\n")
        except Exception as e:
            out.write(json.dumps({"error": type(e).__name__}) + "\n")  # (never the text itself)
        out.flush()


if __name__ == "__main__":
    main()
