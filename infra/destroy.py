#!/usr/bin/env python3
"""
Tears down everything deploy.py created, in reverse order. Safe to re-run - each
step ignores "already gone" errors.

Usage:
    python3 destroy.py --region us-east-1
"""
import argparse

import boto3
import botocore.exceptions

PROJECT = "ai-example-rag"
VECTOR_INDEX_NAME = "chunks"


def log(msg):
    print(f"[destroy] {msg}", flush=True)


def ignore_missing(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except botocore.exceptions.ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if "NotFound" not in code and "NoSuchEntity" not in code and "NoSuchBucket" not in code:
            raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default=boto3.Session().region_name or "us-east-1")
    args = parser.parse_args()

    session = boto3.Session(region_name=args.region)
    account_id = session.client("sts").get_caller_identity()["Account"]
    region = args.region

    s3 = session.client("s3")
    iam = session.client("iam")
    lam = session.client("lambda")
    apigw = session.client("apigatewayv2")
    s3vectors = session.client("s3vectors")

    docs_bucket = f"{PROJECT}-docs-{account_id}"
    vector_bucket = f"{PROJECT}-vectors-{account_id}"
    role_name = f"{PROJECT}-lambda-role"
    api_name = f"{PROJECT}-api"

    log(f"Deleting vector index and bucket: {vector_bucket}")
    ignore_missing(s3vectors.delete_index, vectorBucketName=vector_bucket, indexName=VECTOR_INDEX_NAME)
    ignore_missing(s3vectors.delete_vector_bucket, vectorBucketName=vector_bucket)

    log(f"Deleting HTTP API: {api_name}")
    apis = apigw.get_apis()["Items"]
    for api in apis:
        if api["Name"] == api_name:
            ignore_missing(apigw.delete_api, ApiId=api["ApiId"])

    log("Deleting Lambda functions")
    ignore_missing(lam.delete_function, FunctionName=f"{PROJECT}-ingest")
    ignore_missing(lam.delete_function, FunctionName=f"{PROJECT}-ask")
    ignore_missing(lam.delete_function, FunctionName=f"{PROJECT}-upload")
    ignore_missing(lam.delete_function, FunctionName=f"{PROJECT}-corpus")
    ignore_missing(lam.delete_function, FunctionName=f"{PROJECT}-document")

    log(f"Deleting IAM role: {role_name}")
    ignore_missing(iam.delete_role_policy, RoleName=role_name, PolicyName=f"{PROJECT}-lambda-policy")
    ignore_missing(iam.delete_role, RoleName=role_name)

    log(f"Emptying and deleting S3 bucket: {docs_bucket}")
    try:
        paginator = s3.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=docs_bucket):
            objects = [{"Key": v["Key"], "VersionId": v["VersionId"]} for v in page.get("Versions", [])]
            objects += [{"Key": m["Key"], "VersionId": m["VersionId"]} for m in page.get("DeleteMarkers", [])]
            if objects:
                s3.delete_objects(Bucket=docs_bucket, Delete={"Objects": objects})
        ignore_missing(s3.delete_bucket, Bucket=docs_bucket)
    except botocore.exceptions.ClientError as e:
        if e.response.get("Error", {}).get("Code") != "NoSuchBucket":
            raise

    log("Destroy complete.")


if __name__ == "__main__":
    main()
