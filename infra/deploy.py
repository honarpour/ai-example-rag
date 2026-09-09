#!/usr/bin/env python3
"""
Provisions the AWS backend for the RAG demo: an S3 bucket for source docs, an S3
Vectors bucket+index for embeddings, two Lambda functions (ingest, ask), and an API
Gateway HTTP API exposing POST /ask.

Plain boto3, no CloudFormation/Serverless Framework/CDK - every API call that sets up
the system is visible here. Idempotent: safe to re-run, each step checks for the
resource before creating it.

Usage:
    python3 deploy.py --gen-model-id anthropic.claude-3-5-sonnet-20241022-v2:0
    # or, via env vars instead of flags (also loaded from infra/.env if present):
    GEN_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0 python3 deploy.py

Note: this provisions real, billable AWS resources under your account. Run
destroy.py when you're done to tear everything down.
"""
import argparse
import io
import json
import os
import secrets
import sys
import time
import zipfile

import boto3
import botocore.exceptions

PROJECT = "ai-example-rag"
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBED_DIMENSION = 1024
VECTOR_INDEX_NAME = "chunks"


def log(msg):
    print(f"[deploy] {msg}", flush=True)


def load_dotenv():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


load_dotenv()


def build_lambda_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write("src/common.py", "common.py")
        zf.write("src/ingest.py", "ingest.py")
        zf.write("src/ask.py", "ask.py")
        zf.write("src/upload.py", "upload.py")
        zf.write("src/corpus.py", "corpus.py")
        zf.write("src/document.py", "document.py")
    buf.seek(0)
    return buf.read()


def ensure_docs_bucket(s3, region, account_id):
    name = f"{PROJECT}-docs-{account_id}"
    try:
        s3.head_bucket(Bucket=name)
        log(f"S3 docs bucket already exists: {name}")
    except botocore.exceptions.ClientError:
        log(f"Creating S3 docs bucket: {name}")
        kwargs = {"Bucket": name}
        if region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(**kwargs)
    return name


def ensure_iam_role(iam, account_id, region):
    role_name = f"{PROJECT}-lambda-role"
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }
    try:
        role = iam.get_role(RoleName=role_name)
        log(f"IAM role already exists: {role_name}")
        role_is_new = False
    except iam.exceptions.NoSuchEntityException:
        log(f"Creating IAM role: {role_name}")
        role = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
        )
        role_is_new = True

    permissions_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject"],
                "Resource": f"arn:aws:s3:::{PROJECT}-docs-{account_id}/*",
            },
            {
                "Effect": "Allow",
                "Action": "bedrock:InvokeModel",
                "Resource": "*",
            },
            {
                # Anthropic's Claude models are distributed via AWS Marketplace even
                # when invoked through Bedrock. The FIRST InvokeModel call for a given
                # model in this account auto-subscribes to it - but only if the calling
                # role has these permissions. Without them, InvokeModel fails with
                # AccessDeniedException citing aws-marketplace:ViewSubscriptions/
                # Subscribe, even if you already "have model access" in the Bedrock
                # console. Once the account's subscription activates (can take up to a
                # couple minutes), every role can invoke the model - these permissions
                # only matter for that first activation.
                "Effect": "Allow",
                "Action": [
                    "aws-marketplace:ViewSubscriptions",
                    "aws-marketplace:Subscribe",
                    "aws-marketplace:Unsubscribe",
                ],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3vectors:PutVectors",
                    "s3vectors:QueryVectors",
                    # QueryVectors with returnMetadata=True (which ask.py uses) also
                    # requires GetVectors - AWS docs are explicit that both are needed
                    # together, it's not implied by QueryVectors alone.
                    "s3vectors:GetVectors",
                    "s3vectors:GetIndex",
                    "s3vectors:ListVectors",
                ],
                # Scoped to just this project's vector bucket (and everything under
                # it, e.g. its index) rather than every vector bucket in the account.
                "Resource": f"arn:aws:s3vectors:{region}:{account_id}:bucket/{PROJECT}-vectors-{account_id}/*",
            },
        ],
    }
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName=f"{PROJECT}-lambda-policy",
        PolicyDocument=json.dumps(permissions_policy),
    )
    if role_is_new:
        log("Waiting for IAM role propagation...")
        time.sleep(10)
    else:
        log("Updated IAM role policy, waiting briefly for it to propagate...")
        time.sleep(5)
    return role["Role"]["Arn"]


def ensure_lambda(lam, name, handler, role_arn, zip_bytes, env_vars):
    try:
        fn = lam.get_function(FunctionName=name)
        log(f"Updating Lambda code: {name}")
        # update_function_code is asynchronous - the function sits in
        # LastUpdateStatus=InProgress for a moment, and any other update call
        # (like the config update right after) fails with ResourceConflictException
        # until it settles. The function_updated waiter blocks until that's done.
        lam.update_function_code(FunctionName=name, ZipFile=zip_bytes)
        lam.get_waiter("function_updated").wait(FunctionName=name)
        lam.update_function_configuration(FunctionName=name, Environment={"Variables": env_vars})
        lam.get_waiter("function_updated").wait(FunctionName=name)
        return fn["Configuration"]["FunctionArn"]
    except lam.exceptions.ResourceNotFoundException:
        pass

    log(f"Creating Lambda: {name}")
    for attempt in range(5):
        try:
            fn = lam.create_function(
                FunctionName=name,
                Runtime="python3.12",
                Role=role_arn,
                Handler=handler,
                Code={"ZipFile": zip_bytes},
                Timeout=30,
                MemorySize=256,
                Environment={"Variables": env_vars},
            )
            lam.get_waiter("function_active").wait(FunctionName=name)
            return fn["FunctionArn"]
        except botocore.exceptions.ClientError as e:
            if "role" in str(e).lower() and attempt < 4:
                log("Role not yet propagated, retrying...")
                time.sleep(5)
                continue
            raise


def ensure_s3_trigger(s3, lam, docs_bucket, ingest_arn, account_id, region):
    statement_id = "AllowS3Invoke"
    try:
        lam.add_permission(
            FunctionName=ingest_arn,
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal="s3.amazonaws.com",
            SourceArn=f"arn:aws:s3:::{docs_bucket}",
        )
    except lam.exceptions.ResourceConflictException:
        pass

    s3.put_bucket_notification_configuration(
        Bucket=docs_bucket,
        NotificationConfiguration={
            "LambdaFunctionConfigurations": [{
                "LambdaFunctionArn": ingest_arn,
                "Events": ["s3:ObjectCreated:*"],
                "Filter": {"Key": {"FilterRules": [
                    {"Name": "prefix", "Value": "docs/"},
                    {"Name": "suffix", "Value": ".md"},
                ]}},
            }],
        },
    )
    log("S3 -> ingest Lambda trigger configured")


def ensure_http_api(apigw, lam, routes_to_arns, region, account_id):
    """routes_to_arns: list of (route_key, lambda_arn), e.g. ("POST /ask", ask_arn)."""
    api_name = f"{PROJECT}-api"
    apis = apigw.get_apis()["Items"]
    api = next((a for a in apis if a["Name"] == api_name), None)
    if api:
        log(f"HTTP API already exists: {api_name}")
        api_id = api["ApiId"]
    else:
        log(f"Creating HTTP API: {api_name}")
        api = apigw.create_api(Name=api_name, ProtocolType="HTTP")
        api_id = api["ApiId"]

    existing_integrations = apigw.get_integrations(ApiId=api_id)["Items"]
    existing_routes = apigw.get_routes(ApiId=api_id)["Items"]

    for route_key, lambda_arn in routes_to_arns:
        method, path = route_key.split(" ", 1)
        integration = next((i for i in existing_integrations if i["IntegrationUri"] == lambda_arn), None)
        if not integration:
            integration = apigw.create_integration(
                ApiId=api_id,
                IntegrationType="AWS_PROXY",
                IntegrationUri=lambda_arn,
                PayloadFormatVersion="2.0",
            )
        integration_id = integration["IntegrationId"]

        if not any(r["RouteKey"] == route_key for r in existing_routes):
            apigw.create_route(
                ApiId=api_id,
                RouteKey=route_key,
                Target=f"integrations/{integration_id}",
            )

        try:
            lam.add_permission(
                FunctionName=lambda_arn,
                StatementId="AllowApiGatewayInvoke",
                Action="lambda:InvokeFunction",
                Principal="apigateway.amazonaws.com",
                SourceArn=f"arn:aws:execute-api:{region}:{account_id}:{api_id}/*/{method}{path}",
            )
        except lam.exceptions.ResourceConflictException:
            pass

    stages = apigw.get_stages(ApiId=api_id)["Items"]
    if not any(s["StageName"] == "$default" for s in stages):
        apigw.create_stage(ApiId=api_id, StageName="$default", AutoDeploy=True)

    return f"https://{api_id}.execute-api.{region}.amazonaws.com"


def ensure_vector_store(s3vectors, account_id):
    bucket_name = f"{PROJECT}-vectors-{account_id}"
    try:
        s3vectors.get_vector_bucket(vectorBucketName=bucket_name)
        log(f"S3 vector bucket already exists: {bucket_name}")
    except botocore.exceptions.ClientError:
        log(f"Creating S3 vector bucket: {bucket_name}")
        s3vectors.create_vector_bucket(vectorBucketName=bucket_name)

    try:
        s3vectors.get_index(vectorBucketName=bucket_name, indexName=VECTOR_INDEX_NAME)
        log(f"Vector index already exists: {VECTOR_INDEX_NAME}")
    except botocore.exceptions.ClientError:
        log(f"Creating vector index: {VECTOR_INDEX_NAME}")
        s3vectors.create_index(
            vectorBucketName=bucket_name,
            indexName=VECTOR_INDEX_NAME,
            dataType="float32",
            dimension=EMBED_DIMENSION,
            distanceMetric="cosine",
        )
    return bucket_name


def resolve_api_key(lam, explicit):
    """Shared secret sent as X-API-Key by both demo servers, checked by every
    HTTP-facing Lambda - without it, anyone who finds your API URL can run up your
    Bedrock bill. Reuses the currently-deployed key by default (so re-running deploy
    doesn't silently invalidate .env files you've already set up); pass --api-key to
    set one explicitly, or generate a fresh one only when none exists yet."""
    if explicit:
        return explicit
    try:
        fn = lam.get_function_configuration(FunctionName=f"{PROJECT}-ask")
        current = fn.get("Environment", {}).get("Variables", {}).get("API_KEY")
        if current:
            return current
    except lam.exceptions.ResourceNotFoundException:
        pass
    return secrets.token_urlsafe(24)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gen-model-id", default=os.environ.get("GEN_MODEL_ID"),
                         help="Bedrock model id for a Claude model you've enabled access to, e.g. anthropic.claude-3-5-sonnet-20241022-v2:0. "
                              "Can also be set via the GEN_MODEL_ID environment variable; the flag takes precedence if both are given.")
    parser.add_argument("--api-key", default=os.environ.get("API_KEY"),
                         help="Shared secret required on all API requests. Omit to reuse the existing deployed key, or generate a new random one on first deploy. "
                              "Can also be set via the API_KEY environment variable.")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION") or boto3.Session().region_name or "us-east-1")
    args = parser.parse_args()

    if not args.gen_model_id:
        parser.error("--gen-model-id is required (or set the GEN_MODEL_ID environment variable)")

    session = boto3.Session(region_name=args.region)
    account_id = session.client("sts").get_caller_identity()["Account"]
    region = args.region

    s3 = session.client("s3")
    iam = session.client("iam")
    lam = session.client("lambda")
    apigw = session.client("apigatewayv2")
    s3vectors = session.client("s3vectors")

    log(f"Account: {account_id}, region: {region}")

    docs_bucket = ensure_docs_bucket(s3, region, account_id)
    vector_bucket = ensure_vector_store(s3vectors, account_id)
    role_arn = ensure_iam_role(iam, account_id, region)
    api_key = resolve_api_key(lam, args.api_key)

    zip_bytes = build_lambda_zip()
    env_vars = {
        "VECTOR_BUCKET_NAME": vector_bucket,
        "VECTOR_INDEX_NAME": VECTOR_INDEX_NAME,
        "DOCS_BUCKET_NAME": docs_bucket,
        "EMBED_MODEL_ID": EMBED_MODEL_ID,
        "GEN_MODEL_ID": args.gen_model_id,
        "API_KEY": api_key,
    }

    ingest_arn = ensure_lambda(lam, f"{PROJECT}-ingest", "ingest.handler", role_arn, zip_bytes, env_vars)
    ask_arn = ensure_lambda(lam, f"{PROJECT}-ask", "ask.handler", role_arn, zip_bytes, env_vars)
    upload_arn = ensure_lambda(lam, f"{PROJECT}-upload", "upload.handler", role_arn, zip_bytes, env_vars)
    corpus_arn = ensure_lambda(lam, f"{PROJECT}-corpus", "corpus.handler", role_arn, zip_bytes, env_vars)
    document_arn = ensure_lambda(lam, f"{PROJECT}-document", "document.handler", role_arn, zip_bytes, env_vars)

    ensure_s3_trigger(s3, lam, docs_bucket, ingest_arn, account_id, region)
    api_url = ensure_http_api(apigw, lam, [
        ("POST /ask", ask_arn),
        ("POST /upload", upload_arn),
        ("GET /corpus", corpus_arn),
        ("GET /document", document_arn),
    ], region, account_id)

    print()
    log("Deploy complete.")
    log(f"Docs bucket:  s3://{docs_bucket}")
    log(f"API base URL: {api_url}  (routes: POST /ask, POST /upload, GET /corpus, GET /document)")
    log(f"API key:      {api_key}")
    log("")
    log("Every request needs that key (as header X-API-Key) or the API returns 401 -")
    log("this is what stops a stranger who finds your URL from running up your Bedrock bill.")
    log("")
    log("Next steps:")
    log(f"  aws s3 sync docs s3://{docs_bucket}/docs --region {region}")
    log(f"  printf 'API_URL=%s\\nAPI_KEY=%s\\n' '{api_url}' '{api_key}' > ../python/.env")
    log(f"  printf 'API_URL=%s\\nAPI_KEY=%s\\n' '{api_url}' '{api_key}' > ../node/.env")


if __name__ == "__main__":
    try:
        main()
    except botocore.exceptions.NoCredentialsError:
        print("No AWS credentials found. Configure them with `aws configure` first.", file=sys.stderr)
        sys.exit(1)
