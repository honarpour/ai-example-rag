"""
Ask Lambda: HTTP API POST /ask.
Embeds the question, runs a k-NN search against the S3 Vectors index, builds an
augmented prompt from the retrieved chunks, and calls a Claude model on Bedrock to
generate a grounded answer.

Scaling note: S3 Vectors is used here because it fits a demo/low-query-volume workload
at zero idle cost. If query volume or latency requirements grow, AWS supports importing
S3 Vectors data directly into Amazon OpenSearch Serverless for a faster, more
feature-complete ANN engine (hybrid search, filters, tunable recall) - a supported data
migration, not a from-scratch re-embed. See the README's "Scaling path" section.
"""
import json
import os

import boto3

from common import is_authorized, parse_body, unauthorized_response

VECTOR_BUCKET_NAME = os.environ["VECTOR_BUCKET_NAME"]
VECTOR_INDEX_NAME = os.environ["VECTOR_INDEX_NAME"]
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
GEN_MODEL_ID_DEFAULT = os.environ["GEN_MODEL_ID"]

bedrock = boto3.client("bedrock-runtime")
s3vectors = boto3.client("s3vectors")

SYSTEM_PROMPT = (
    "You are a helpful assistant answering questions about Acme Cloud Corp. using "
    "only the context provided below. If the context doesn't contain the answer, say "
    "so plainly rather than guessing. Cite which document each part of your answer "
    "comes from."
)


def embed(text):
    body = json.dumps({"inputText": text})
    response = bedrock.invoke_model(modelId=EMBED_MODEL_ID, body=body)
    payload = json.loads(response["body"].read())
    return payload["embedding"]


def build_prompt(query, sources):
    context = "\n\n".join(
        f"[Source: {s['doc_id']}]\n{s['text']}" for s in sources
    )
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {query}"
    )


def generate(prompt, model_id):
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    })
    response = bedrock.invoke_model(modelId=model_id, body=body)
    payload = json.loads(response["body"].read())
    return payload["content"][0]["text"]


def resolve_model_id(requested):
    """Lets the dashboard override the generation model per-request. Restricted to
    Claude models by name, since this endpoint has no auth and a fully open model_id
    would let any caller invoke arbitrary (possibly expensive) Bedrock models."""
    if not requested:
        return GEN_MODEL_ID_DEFAULT
    if "claude" not in requested.lower():
        raise ValueError("model_id must be a Claude model")
    return requested


def handler(event, context):
    if not is_authorized(event):
        return unauthorized_response()
    try:
        body = parse_body(event)
        query = body["query"]
        k = int(body.get("k", 3))
        model_id = resolve_model_id(body.get("model_id"))

        query_vector = embed(query)
        result = s3vectors.query_vectors(
            vectorBucketName=VECTOR_BUCKET_NAME,
            indexName=VECTOR_INDEX_NAME,
            queryVector={"float32": query_vector},
            topK=k,
            returnMetadata=True,
            returnDistance=True,
        )

        sources = [
            {
                "chunk_id": v["key"],
                "doc_id": v["metadata"]["doc_id"],
                "text": v["metadata"]["text"],
                "score": 1 - v["distance"],
            }
            for v in result.get("vectors", [])
        ]

        prompt = build_prompt(query, sources)
        answer = generate(prompt, model_id)

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "answer": answer,
                "sources": sources,
                "prompt": prompt,
                "model_id": model_id,
            }),
        }
    except Exception as exc:  # noqa: BLE001 - surface the error to the caller for a demo
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(exc)}),
        }
