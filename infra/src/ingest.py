"""
Ingest Lambda: triggered on S3 ObjectCreated under docs/.
Reads a markdown doc, splits it into paragraph chunks, embeds each chunk with
Bedrock Titan Embeddings, and writes the chunk + its vector into the S3 Vectors index.
"""
import json
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import boto3

VECTOR_BUCKET_NAME = os.environ["VECTOR_BUCKET_NAME"]
VECTOR_INDEX_NAME = os.environ["VECTOR_INDEX_NAME"]
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")

s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime")
s3vectors = boto3.client("s3vectors")


def chunk_document(text):
    """Split a markdown doc into paragraph-level chunks, dropping the H1 title line."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return [p for p in paragraphs if not p.startswith("# ")]


def embed(text):
    body = json.dumps({"inputText": text})
    response = bedrock.invoke_model(modelId=EMBED_MODEL_ID, body=body)
    payload = json.loads(response["body"].read())
    return payload["embedding"]


def handler(event, context):
    indexed = 0
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        if not key.endswith(".md"):
            continue

        doc_id = os.path.splitext(os.path.basename(key))[0]
        obj = s3.get_object(Bucket=bucket, Key=key)
        text = obj["Body"].read().decode("utf-8")

        # Bedrock InvokeModel calls are independent, I/O-bound network round trips,
        # so embedding chunks concurrently (instead of one at a time in a loop) cuts
        # both indexing latency and this Lambda's billed duration roughly by a factor
        # of however many chunks run in parallel.
        chunks = chunk_document(text)
        with ThreadPoolExecutor(max_workers=8) as pool:
            embeddings = list(pool.map(embed, chunks))

        vectors = [
            {
                "key": f"{doc_id}#{i}",
                "data": {"float32": embedding},
                "metadata": {"doc_id": doc_id, "text": chunk_text},
            }
            for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings))
        ]

        if vectors:
            s3vectors.put_vectors(
                vectorBucketName=VECTOR_BUCKET_NAME,
                indexName=VECTOR_INDEX_NAME,
                vectors=vectors,
            )
            indexed += len(vectors)

    return {"indexed_chunks": indexed}
