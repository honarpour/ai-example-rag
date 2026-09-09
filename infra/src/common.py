"""
Shared helpers for the HTTP-facing Lambdas (ask, upload, corpus, document - not
ingest, which is S3-triggered and needs none of this). Bundled into the same
deployment zip as a flat module (see deploy.py's build_lambda_zip), so a plain
`from common import ...` works from any of them.
"""
import base64
import hmac
import json
import os

API_KEY = os.environ.get("API_KEY", "")


def is_authorized(event):
    """Shared-secret check, not real IAM auth - just enough to stop a stranger who
    finds this URL from running up your Bedrock bill. Both demo servers send this
    header automatically once API_KEY is set in their .env."""
    provided = (event.get("headers") or {}).get("x-api-key", "")
    return bool(API_KEY) and hmac.compare_digest(provided, API_KEY)


def unauthorized_response():
    return {
        "statusCode": 401,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": "unauthorized"}),
    }


def parse_body(event):
    """API Gateway HTTP API base64-encodes the body for some requests (e.g. when the
    caller doesn't send Content-Type: application/json) - decode it first so callers
    that don't set that header don't hit a confusing JSON parse error."""
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw)
