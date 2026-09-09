"""
Corpus Lambda: HTTP API GET /corpus.
Lists what's actually indexed in the S3 Vectors index right now, grouped by
document. This gives the frontend a live view of the knowledge base instead of a
static snapshot, so a document uploaded via upload.py shows up here once
ingestion finishes - no separate "add to the UI" step needed.

Also returns the deployed default generation model id, so the dashboard's model
override field can show what will actually be used rather than a vague placeholder.
"""
import json
import os
from collections import defaultdict

import boto3

from common import is_authorized, unauthorized_response

VECTOR_BUCKET_NAME = os.environ["VECTOR_BUCKET_NAME"]
VECTOR_INDEX_NAME = os.environ["VECTOR_INDEX_NAME"]
GEN_MODEL_ID_DEFAULT = os.environ.get("GEN_MODEL_ID", "")

s3vectors = boto3.client("s3vectors")


def _preview(text, limit=130):
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[:limit].rsplit(" ", 1)[0] + "…"


def _title(doc_id):
    return doc_id.replace("-", " ").replace("_", " ").title()


def handler(event, context):
    if not is_authorized(event):
        return unauthorized_response()
    by_doc = defaultdict(list)
    next_token = None
    while True:
        kwargs = {
            "vectorBucketName": VECTOR_BUCKET_NAME,
            "indexName": VECTOR_INDEX_NAME,
            "returnMetadata": True,
        }
        if next_token:
            kwargs["nextToken"] = next_token
        page = s3vectors.list_vectors(**kwargs)
        for v in page.get("vectors", []):
            meta = v.get("metadata", {})
            by_doc[meta.get("doc_id", "unknown")].append({
                "chunk_id": v["key"],
                "preview": _preview(meta.get("text", "")),
            })
        next_token = page.get("nextToken")
        if not next_token:
            break

    docs = [
        {
            "doc_id": doc_id,
            "title": _title(doc_id),
            "chunks": sorted(chunks, key=lambda c: c["chunk_id"]),
        }
        for doc_id, chunks in sorted(by_doc.items())
    ]

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"docs": docs, "default_model_id": GEN_MODEL_ID_DEFAULT}),
    }
