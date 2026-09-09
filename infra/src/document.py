"""
Document Lambda: HTTP API GET /document?doc_id=X.
Returns the original source markdown for one document straight from the S3 docs
bucket - not reconstructed from chunks - so what you see in the dashboard is exactly
what was ingested (headings, formatting, and all).
"""
import json
import os
import re

import boto3

from common import is_authorized, unauthorized_response

DOCS_BUCKET_NAME = os.environ["DOCS_BUCKET_NAME"]

s3 = boto3.client("s3")


def _safe_doc_id(doc_id):
    return re.sub(r"[^A-Za-z0-9._-]", "", doc_id or "")


def handler(event, context):
    if not is_authorized(event):
        return unauthorized_response()
    params = event.get("queryStringParameters") or {}
    doc_id = _safe_doc_id(params.get("doc_id"))
    if not doc_id:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "doc_id query parameter is required"}),
        }

    try:
        obj = s3.get_object(Bucket=DOCS_BUCKET_NAME, Key=f"docs/{doc_id}.md")
        content = obj["Body"].read().decode("utf-8")
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"doc_id": doc_id, "content": content}),
        }
    except s3.exceptions.NoSuchKey:
        return {
            "statusCode": 404,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"no document found for doc_id={doc_id}"}),
        }
