#!/usr/bin/env python3
"""
Tiny golden-set eval for the deployed RAG backend. Fires a fixed set of questions at
POST /ask (the same endpoint the dashboard calls) and checks two things per question:

  - retrieval: did the expected document show up among the returned sources?
  - groundedness: does the answer contain the fact it should, or (for questions with
    no answer in the corpus) does it actually decline rather than guess?

The question set is hand-written against infra/docs/*.md, so it doubles as a
readable check that the corpus, chunking, and prompt are all still working the way
the README describes. Stdlib-only, same as the demo servers - no eval framework, no
LLM judge, just fixed facts checked with substring matching.

Usage:
    python3 eval.py
    # API_URL/API_KEY come from the environment, infra/.env, or python/.env (in that
    # order) - the same places deploy.py prints them to.
"""
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def load_dotenv(path):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


# API_URL/API_KEY aren't normally written to infra/.env (only GEN_MODEL_ID/API_KEY
# are) - they live in python/.env once deploy.py prints them, so fall back there.
load_dotenv(os.path.join(HERE, ".env"))
load_dotenv(os.path.join(HERE, "..", "python", ".env"))

API_URL = os.environ.get("API_URL", "").rstrip("/")
API_KEY = os.environ.get("API_KEY", "")

REFUSAL_PHRASES = [
    "don't know", "do not know", "doesn't contain", "does not contain",
    "no information", "not mentioned", "not provided", "cannot find",
    "can't find", "i don't have", "not covered", "isn't covered",
    "context doesn't", "context does not",
]

# Each case checks either retrieval + groundedness against a known doc, or (for
# out-of-scope questions) that the model declines instead of guessing.
CASES = [
    {
        "query": "How many days do I have to submit an expense report?",
        "expect_doc_ids": ["expense-policy"],
        "must_contain": ["30"],
    },
    {
        "query": "What is the daily meal reimbursement cap during business travel?",
        "expect_doc_ids": ["expense-policy"],
        "must_contain": ["75"],
    },
    {
        "query": "Who is assigned to help new employees ramp up during their first two weeks?",
        "expect_doc_ids": ["onboarding-guide"],
        "must_contain": ["buddy"],
    },
    {
        "query": "How soon must new employees complete compliance training?",
        "expect_doc_ids": ["onboarding-guide"],
        "must_contain": ["10"],
    },
    {
        "query": "How much free storage does Acme Cloud give on the Starter plan?",
        "expect_doc_ids": ["product-faq"],
        "must_contain": ["15"],
    },
    {
        "query": "How long does Acme retain file version history on the Business plan?",
        "expect_doc_ids": ["product-faq"],
        "must_contain": ["180"],
    },
    {
        "query": "How soon must a suspected security incident be reported after discovery?",
        "expect_doc_ids": ["security-policy"],
        "must_contain": ["1 hour"],
    },
    {
        "query": "How often is engineers' write access to production databases reviewed?",
        "expect_doc_ids": ["security-policy"],
        "must_contain": ["quarter"],
    },
    {
        "query": "How many PTO days do full-time employees accrue per year?",
        "expect_doc_ids": ["vacation-policy"],
        "must_contain": ["21"],
    },
    {
        "query": "How many weeks of paid parental leave are new parents eligible for?",
        "expect_doc_ids": ["vacation-policy"],
        "must_contain": ["12"],
    },
    {
        "query": "What is Acme Cloud Corp.'s stock ticker symbol?",
        "expect_answerable": False,
    },
    {
        "query": "Who is the CEO of Acme Cloud Corp.?",
        "expect_answerable": False,
    },
    {
        "query": "What programming language is Acme's backend written in?",
        "expect_answerable": False,
    },
]


def ask(query, k=3):
    req = urllib.request.Request(
        API_URL + "/ask",
        data=json.dumps({"query": query, "k": k}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def check(case):
    """Returns (retrieval_ok, groundedness_ok, detail) for one case."""
    result = ask(case["query"])
    answer = result["answer"]
    doc_ids = {s["doc_id"] for s in result["sources"]}

    if case.get("expect_answerable", True):
        retrieval_ok = bool(doc_ids & set(case["expect_doc_ids"]))
        groundedness_ok = all(kw.lower() in answer.lower() for kw in case["must_contain"])
        detail = f"sources={sorted(doc_ids)} answer={answer[:120]!r}"
    else:
        retrieval_ok = True  # no expected doc for an out-of-scope question
        groundedness_ok = any(p in answer.lower() for p in REFUSAL_PHRASES)
        detail = f"answer={answer[:120]!r}"

    return retrieval_ok, groundedness_ok, detail


def main():
    if not API_URL or not API_KEY:
        print(
            "API_URL/API_KEY not set. Set them in the environment, infra/.env, or "
            "python/.env (same values deploy.py printed).",
            file=sys.stderr,
        )
        sys.exit(1)

    passed = 0
    failed = 0
    for case in CASES:
        query = case["query"]
        try:
            retrieval_ok, groundedness_ok, detail = check(case)
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError) as exc:
            print(f"FAIL  {query}\n      error: {exc}")
            failed += 1
            continue

        ok = retrieval_ok and groundedness_ok
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {query}")
        if not ok:
            if not retrieval_ok:
                print(f"      retrieval:    expected one of {case['expect_doc_ids']}")
            if not groundedness_ok:
                print("      groundedness: failed")
            print(f"      {detail}")

        if ok:
            passed += 1
        else:
            failed += 1

    total = passed + failed
    print(f"\n{passed}/{total} passed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
