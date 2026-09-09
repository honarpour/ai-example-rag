"""
Upload Lambda: HTTP API POST /upload.
Accepts {filename, content} JSON and writes the document to the S3 docs bucket. The
existing S3 ObjectCreated trigger on the ingest Lambda (see ingest.py) picks it up
automatically from there - this endpoint doesn't duplicate any chunking/embedding
logic, it just puts the file where ingestion already watches.
"""
import json
import os
import re

import boto3

from common import is_authorized, parse_body, unauthorized_response

DOCS_BUCKET_NAME = os.environ["DOCS_BUCKET_NAME"]

s3 = boto3.client("s3")


def _safe_filename(filename):
    name = os.path.basename(filename or "").strip()
    name = re.sub(r"[^A-Za-z0-9._-]", "-", name)
    if not name or name in (".", ".."):
        name = "document"
    if not name.endswith(".md"):
        name += ".md"
    return name


def handler(event, context):
    if not is_authorized(event):
        return unauthorized_response()
    try:
        body = parse_body(event)
        content = body.get("content", "")
        if not content.strip():
            raise ValueError("content is required and cannot be empty")

        filename = _safe_filename(body.get("filename", "document.md"))

        s3.put_object(
            Bucket=DOCS_BUCKET_NAME,
            Key=f"docs/{filename}",
            Body=content.encode("utf-8"),
            ContentType="text/markdown",
        )

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "status": "uploaded",
                "filename": filename,
                "doc_id": filename[:-3],
                "message": "Uploaded. Indexing runs asynchronously and usually finishes within a few seconds.",
            }),
        }
    except Exception as exc:  # noqa: BLE001 - surface the error to the caller for a demo
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(exc)}),
        }
