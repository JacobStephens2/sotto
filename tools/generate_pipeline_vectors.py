#!/usr/bin/env python3
"""Generate pipeline-vectors.json: the contract between this server's text
pipeline (the reference implementation) and ports of it (sotto-android).

For each corpus case it records clean_markdown(input) and chunk(cleaned, 1000).
Ports must reproduce these byte-for-byte. Regenerate ONLY here, commit the JSON
in both repos, and publish the sha256 so drift fails CI on the port's side.

    .venv/bin/python tools/generate_pipeline_vectors.py
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LECTOR_RESUME", "0")
import app  # noqa: E402  (the reference implementation)

KOKORO_LIMIT = 1000

CORPUS = {
    "plain-paragraph": "This is a plain paragraph with nothing special in it at all.",
    "heading-levels": "# Title One\n\nBody text.\n\n## Sub Two\n\nMore body.\n\n###### Deep Six\n\nEnd.",
    "links-and-urls": "See [the spec](https://example.com/spec) and also https://raw.example.com/x?a=1 inline.\nA [nested [bracket] link](http://x.y) too.",
    "table-simple": "| Name | Value |\n|------|-------|\n| alpha | one |\n| beta | two |",
    "table-ragged": "| only | row |\n|:--|--:|\n|  spaced  |  cells  |",
    "blockquote-and-bullets": "> A quoted line\n> another\n\n- first bullet\n* star bullet\n  - indented dash",
    "code-fence-and-rule": "Before\n```\ncode line stays? fence line goes\n```\n---\nAfter",
    "emphasis-soup": "This **bold** and __also bold__ and *ital* and _ital_ and mid*star and snake_case_word stay sane.",
    "inline-code": "Use `app.py` and `LECTOR_RESUME=1` carefully.",
    "section-symbol": "Per §102 and §105, see sections.",
    "circled-digits": "Items ① and ② and ⑨ are enumerated.",
    "md-file-refs": "Read career-advancement-plan-r3.md and notes.md today.",
    "arrows-and-compare": "a → b ↔ c, x ≤ 5, y ≥ 2, 3×4, 50%",
    "dashes-and-ranges": "pages 3-7, then 1990–1995, em—dash, mid-word-hyphens stay",
    "money-and-k": "Costs $1,234.56 or maybe 10K plus 3+ extras.",
    "acronyms": "Write 3 ADRs; one ADR per choice. 5 hr/wk on K8s and IaC; review JDs, one JD, PR #148.",
    "short-line-punctuation": "No terminal punctuation here\nAlready has period.\nHas colon:\nHas comma,\n" + ("x" * 130),
    "entities-and-middot": "A &middot; B · C &nbsp; D &amp; E &emsp; F",
    "whitespace-collapse": "Too   many\tspaces\n\n\n\n\nand blank lines.",
    "unicode-text": "Café naïve résumé — done. Привет 你好.",
    "empty-and-blank": "\n\n   \n",
    "long-document": "\n\n".join(
        f"Paragraph {i}. " + "A sentence that runs along quite nicely with enough words to matter. " * 6
        for i in range(12)),
    "single-monster-paragraph": "One enormous sentence-free paragraph " + "word " * 700,
    "sentence-split-boundaries": "Short one. Another short one! A third? "
        + "Then a very long sentence that should still be kept whole when chunking because splitting happens at sentence boundaries only. " * 12,
}


def main():
    out = {
        "_meta": {
            "reference": "sotto server app.py clean_markdown()+chunk()",
            "kokoro_chunk_limit": KOKORO_LIMIT,
            "note": "regenerate only via tools/generate_pipeline_vectors.py in the server repo",
        },
        "cases": [],
    }
    for name, src in sorted(CORPUS.items()):
        cleaned = app.clean_markdown(src)
        out["cases"].append({
            "name": name,
            "input": src,
            "cleaned": cleaned,
            "chunks": app.chunk(cleaned, KOKORO_LIMIT),
        })
    path = os.environ.get("VECTORS_OUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline-vectors.json")
    blob = json.dumps(out, ensure_ascii=False, indent=1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(blob + "\n")
    digest = hashlib.sha256((blob + "\n").encode()).hexdigest()
    print(f"wrote {path}")
    print(f"cases: {len(out['cases'])}")
    print(f"sha256: {digest}")


if __name__ == "__main__":
    main()
