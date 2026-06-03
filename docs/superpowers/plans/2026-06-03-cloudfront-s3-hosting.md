# CloudFront + S3 Hosting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--stage hosting` option to `setup_aws_resources.py` that provisions an S3 bucket + CloudFront distribution with OAC, builds the React app, and deploys it.

**Architecture:** Extend the existing `AWSResourcesSetup` class with a `setup_hosting()` method that idempotently creates the infrastructure (bucket, OAC, distribution, bucket policy), runs the React build, syncs output to S3 with correct content types/cache headers, and invalidates the CloudFront cache.

**Tech Stack:** Python 3, boto3 (S3, CloudFront), subprocess (npm build), existing `setup_aws_resources.py` patterns

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `setup_aws_resources.py` | Add `setup_hosting()` method, CloudFront client, new CLI args/stage |

Single file modification — follows the existing pattern where all infrastructure lives in this one script.

---

## Task 1: Add CloudFront client and hosting bucket creation

**Files:**
- Modify: `setup_aws_resources.py:21-32` (add cloudfront client to `__init__`)
- Modify: `setup_aws_resources.py:478-515` (reuse existing `create_s3_bucket` pattern)

- [ ] **Step 1: Add cloudfront client to `__init__`**

In `setup_aws_resources.py`, add to the `__init__` method after the `self.kvs` line (line 32):

```python
        self.cloudfront = boto3.client('cloudfront')
```

- [ ] **Step 2: Add method to create hosting bucket with public access blocked**

Add after the existing `create_s3_bucket` method (after line 515):

```python
    def create_hosting_bucket(self, bucket_name):
        """Create S3 bucket for static hosting with all public access blocked."""
        try:
            self.s3.head_bucket(Bucket=bucket_name)
            print(f"Hosting bucket already exists: {bucket_name}")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code in ('404', 'NoSuchBucket'):
                if self.aws_region == 'us-east-1':
                    self.s3.create_bucket(Bucket=bucket_name)
                else:
                    self.s3.create_bucket(
                        Bucket=bucket_name,
                        CreateBucketConfiguration={'LocationConstraint': self.aws_region}
                    )
                print(f"Created hosting bucket: {bucket_name}")
            else:
                raise

        self.s3.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': True,
                'IgnorePublicAcls': True,
                'BlockPublicPolicy': True,
                'RestrictPublicBuckets': True,
            }
        )
        print(f"Public access blocked on: {bucket_name}")
        return bucket_name
```

- [ ] **Step 3: Commit**

```bash
git add setup_aws_resources.py
git commit -m "feat(hosting): add cloudfront client and hosting bucket creation"
```

---

## Task 2: OAC and CloudFront distribution creation

**Files:**
- Modify: `setup_aws_resources.py` (add methods after `create_hosting_bucket`)

- [ ] **Step 1: Add method to find or create OAC**

```python
    def find_or_create_oac(self, oac_name):
        """Find existing OAC by name or create a new one."""
        try:
            response = self.cloudfront.list_origin_access_controls()
            for item in response.get('OriginAccessControlList', {}).get('Items', []):
                if item['Name'] == oac_name:
                    oac_id = item['Id']
                    print(f"Using existing OAC: {oac_id}")
                    return oac_id
        except ClientError:
            pass

        response = self.cloudfront.create_origin_access_control(
            OriginAccessControlConfig={
                'Name': oac_name,
                'Description': f'OAC for {self.project_name} dashboard',
                'SigningProtocol': 'sigv4',
                'SigningBehavior': 'always',
                'OriginAccessControlOriginType': 's3',
            }
        )
        oac_id = response['OriginAccessControl']['Id']
        print(f"Created OAC: {oac_id}")
        return oac_id
```

- [ ] **Step 2: Add method to find existing distribution by tag**

```python
    def find_distribution_by_tag(self):
        """Find an existing CloudFront distribution tagged with this project."""
        try:
            paginator = self.cloudfront.get_paginator('list_distributions')
            for page in paginator.paginate():
                dist_list = page.get('DistributionList', {})
                for dist in dist_list.get('Items', []):
                    dist_id = dist['Id']
                    try:
                        tags_resp = self.cloudfront.list_tags_for_resource(
                            Resource=dist['ARN']
                        )
                        for tag in tags_resp['Tags'].get('Items', []):
                            if tag['Key'] == 'project' and tag['Value'] == self.project_name:
                                print(f"Found existing distribution: {dist_id}")
                                return dist_id, dist['ARN'], dist['DomainName']
                    except ClientError:
                        continue
        except ClientError:
            pass
        return None, None, None
```

- [ ] **Step 3: Add method to create or update CloudFront distribution**

```python
    def create_or_update_distribution(self, bucket_name, oac_id):
        """Create CloudFront distribution or return existing one."""
        existing_id, existing_arn, existing_domain = self.find_distribution_by_tag()
        if existing_id:
            print(f"Distribution already exists: https://{existing_domain}")
            return existing_id, existing_arn, existing_domain

        origin_domain = f'{bucket_name}.s3.{self.aws_region}.amazonaws.com'
        caller_reference = f'{self.project_name}-dashboard-{self.account_id}'

        response = self.cloudfront.create_distribution_with_tags(
            DistributionConfigWithTags={
                'DistributionConfig': {
                    'CallerReference': caller_reference,
                    'Comment': f'{self.project_name} dashboard',
                    'Enabled': True,
                    'DefaultRootObject': 'index.html',
                    'HttpVersion': 'http2',
                    'PriceClass': 'PriceClass_100',
                    'Origins': {
                        'Quantity': 1,
                        'Items': [{
                            'Id': f'{bucket_name}-origin',
                            'DomainName': origin_domain,
                            'OriginAccessControlId': oac_id,
                            'S3OriginConfig': {
                                'OriginAccessIdentity': '',
                            },
                        }],
                    },
                    'DefaultCacheBehavior': {
                        'TargetOriginId': f'{bucket_name}-origin',
                        'ViewerProtocolPolicy': 'redirect-to-https',
                        'AllowedMethods': {
                            'Quantity': 2,
                            'Items': ['GET', 'HEAD'],
                            'CachedMethods': {
                                'Quantity': 2,
                                'Items': ['GET', 'HEAD'],
                            },
                        },
                        'CachePolicyId': '658327ea-f89d-4fab-a63d-7e88639e58f6',
                        'Compress': True,
                        'ForwardedValues': None,
                    },
                    'CustomErrorResponses': {
                        'Quantity': 2,
                        'Items': [
                            {
                                'ErrorCode': 403,
                                'ResponsePagePath': '/index.html',
                                'ResponseCode': '200',
                                'ErrorCachingMinTTL': 10,
                            },
                            {
                                'ErrorCode': 404,
                                'ResponsePagePath': '/index.html',
                                'ResponseCode': '200',
                                'ErrorCachingMinTTL': 10,
                            },
                        ],
                    },
                    'ViewerCertificate': {
                        'CloudFrontDefaultCertificate': True,
                    },
                },
                'Tags': {
                    'Items': [
                        {'Key': 'project', 'Value': self.project_name},
                    ],
                },
            }
        )
        dist = response['Distribution']
        dist_id = dist['Id']
        dist_arn = dist['ARN']
        dist_domain = dist['DomainName']
        print(f"Created CloudFront distribution: {dist_id}")
        print(f"  URL: https://{dist_domain}")
        print(f"  Note: May take 5-10 minutes to fully deploy")
        return dist_id, dist_arn, dist_domain
```

- [ ] **Step 4: Commit**

```bash
git add setup_aws_resources.py
git commit -m "feat(hosting): add OAC and CloudFront distribution creation"
```

---

## Task 3: Bucket policy for OAC

**Files:**
- Modify: `setup_aws_resources.py` (add method after distribution creation)

- [ ] **Step 1: Add method to set bucket policy**

```python
    def set_hosting_bucket_policy(self, bucket_name, distribution_arn):
        """Set bucket policy allowing only the CloudFront distribution access."""
        policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "cloudfront.amazonaws.com"},
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket_name}/*",
                "Condition": {
                    "StringEquals": {
                        "AWS:SourceArn": distribution_arn
                    }
                }
            }]
        }
        self.s3.put_bucket_policy(
            Bucket=bucket_name,
            Policy=json.dumps(policy)
        )
        print(f"Set bucket policy for CloudFront OAC access")
```

- [ ] **Step 2: Commit**

```bash
git add setup_aws_resources.py
git commit -m "feat(hosting): add OAC bucket policy"
```

---

## Task 4: Build and sync React app to S3

**Files:**
- Modify: `setup_aws_resources.py` (add build/sync methods)

- [ ] **Step 1: Add import for subprocess and os.walk at the top of the file**

Add `import subprocess` and `import os` to the imports section (os is likely already imported but subprocess is not):

```python
import subprocess
```

- [ ] **Step 2: Add method to build the React app**

```python
    def build_react_app(self):
        """Build the React app. Installs dependencies if needed."""
        react_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'react-web')

        if not os.path.isdir(os.path.join(react_dir, 'node_modules')):
            print("Installing React app dependencies...")
            subprocess.run(['npm', 'install'], cwd=react_dir, check=True)

        print("Building React app...")
        subprocess.run(['npm', 'run', 'build'], cwd=react_dir, check=True)

        dist_dir = os.path.join(react_dir, 'dist')
        if not os.path.isdir(dist_dir):
            raise RuntimeError(f"Build output not found at {dist_dir}")
        print(f"Build complete: {dist_dir}")
        return dist_dir
```

- [ ] **Step 3: Add method to sync build output to S3**

```python
    def sync_to_s3(self, dist_dir, bucket_name):
        """Upload build output to S3 with correct content types and cache headers."""
        content_type_map = {
            '.html': 'text/html',
            '.js': 'application/javascript',
            '.css': 'text/css',
            '.json': 'application/json',
            '.svg': 'image/svg+xml',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.ico': 'image/x-icon',
            '.woff': 'font/woff',
            '.woff2': 'font/woff2',
            '.ttf': 'font/ttf',
            '.map': 'application/json',
        }

        file_count = 0
        for root, _dirs, files in os.walk(dist_dir):
            for filename in files:
                filepath = os.path.join(root, filename)
                key = os.path.relpath(filepath, dist_dir)

                ext = os.path.splitext(filename)[1].lower()
                content_type = content_type_map.get(ext, 'application/octet-stream')

                if filename == 'index.html':
                    cache_control = 'no-cache'
                else:
                    cache_control = 'max-age=31536000, immutable'

                with open(filepath, 'rb') as f:
                    self.s3.put_object(
                        Bucket=bucket_name,
                        Key=key,
                        Body=f.read(),
                        ContentType=content_type,
                        CacheControl=cache_control,
                    )
                file_count += 1

        print(f"Uploaded {file_count} files to s3://{bucket_name}/")
```

- [ ] **Step 4: Add method to invalidate CloudFront cache**

```python
    def invalidate_cloudfront_cache(self, distribution_id):
        """Create a CloudFront invalidation for all paths."""
        import time as _time
        response = self.cloudfront.create_invalidation(
            DistributionId=distribution_id,
            InvalidationBatch={
                'Paths': {
                    'Quantity': 1,
                    'Items': ['/*'],
                },
                'CallerReference': str(int(_time.time())),
            }
        )
        invalidation_id = response['Invalidation']['Id']
        print(f"Created cache invalidation: {invalidation_id}")
```

- [ ] **Step 5: Commit**

```bash
git add setup_aws_resources.py
git commit -m "feat(hosting): add React build, S3 sync, and cache invalidation"
```

---

## Task 5: Orchestrate with `setup_hosting()` and CLI integration

**Files:**
- Modify: `setup_aws_resources.py` (add orchestrator method and update `main()`)

- [ ] **Step 1: Add the `setup_hosting()` orchestrator method**

Add after the `sync_to_s3` method:

```python
    def setup_hosting(self, hosting_bucket=None):
        """Provision S3 + CloudFront hosting and deploy the React app."""
        bucket_name = hosting_bucket or f'{self.project_name}-dashboard'
        oac_name = f'{self.project_name}-dashboard-oac'

        print(f"\n{'='*60}")
        print(f"Setting up CloudFront + S3 hosting")
        print(f"{'='*60}\n")

        # 1. Create bucket
        self.create_hosting_bucket(bucket_name)

        # 2. Create OAC
        oac_id = self.find_or_create_oac(oac_name)

        # 3. Create/find distribution
        dist_id, dist_arn, dist_domain = self.create_or_update_distribution(bucket_name, oac_id)

        # 4. Set bucket policy
        self.set_hosting_bucket_policy(bucket_name, dist_arn)

        # 5. Build React app
        dist_dir = self.build_react_app()

        # 6. Sync to S3
        self.sync_to_s3(dist_dir, bucket_name)

        # 7. Invalidate cache
        self.invalidate_cloudfront_cache(dist_id)

        print(f"\n{'='*60}")
        print(f"Dashboard deployed!")
        print(f"URL: https://{dist_domain}")
        print(f"{'='*60}\n")
        return dist_domain
```

- [ ] **Step 2: Update `main()` to add `--stage hosting` and `--hosting-bucket` args**

Replace the `main()` function (lines 727-749):

```python
def main():
    parser = argparse.ArgumentParser(description='Setup AWS resources for Ubuntu Core Greengrass Demo project')
    parser.add_argument('--region', default='eu-west-1', help='AWS region')
    parser.add_argument('--project-name', default='ubuntu-core-gg-demo', help='Project name prefix')
    parser.add_argument('--s3-bucket', help='S3 bucket name for images')
    parser.add_argument('--kvs-stream-name', help='KVS stream name (default: <project-name>-stream)')
    parser.add_argument('--demo-password', help='Password for demo user (must be 8+ chars with uppercase, lowercase, number, and special character)')
    parser.add_argument('--stage', choices=['setup', 'hosting'], help='Run a specific stage only')
    parser.add_argument('--hosting-bucket', help='S3 bucket name for dashboard hosting (default: <project-name>-dashboard)')

    args = parser.parse_args()

    try:
        setup = AWSResourcesSetup(args.region, args.project_name)

        if args.stage == 'hosting':
            setup.setup_hosting(args.hosting_bucket)
        else:
            # Default: full setup
            demo_password = args.demo_password
            if not demo_password:
                demo_password = getpass.getpass('Enter password for demo user (demo@example.com): ')
            setup.setup_all(args.s3_bucket, demo_password, args.kvs_stream_name)
    except Exception as e:
        print(f"Setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify script syntax**

Run: `python3 -c "import ast; ast.parse(open('setup_aws_resources.py').read())"`
Expected: No output (valid syntax)

- [ ] **Step 4: Commit**

```bash
git add setup_aws_resources.py
git commit -m "feat(hosting): add setup_hosting orchestrator and --stage hosting CLI"
```

---

## Task 6: End-to-end test

**Files:**
- No source changes — validation only

- [ ] **Step 1: Verify script runs with --help**

Run: `python3 setup_aws_resources.py --help`
Expected: Shows `--stage {setup,hosting}` and `--hosting-bucket` options.

- [ ] **Step 2: Run hosting deployment**

Run: `python3 setup_aws_resources.py --stage hosting --region eu-west-1`
Expected:
```
============================================================
Setting up CloudFront + S3 hosting
============================================================

Created hosting bucket: ubuntu-core-gg-demo-dashboard
Public access blocked on: ubuntu-core-gg-demo-dashboard
Created OAC: ...
Created CloudFront distribution: ...
  URL: https://d1234abcdef.cloudfront.net
  Note: May take 5-10 minutes to fully deploy
Set bucket policy for CloudFront OAC access
Building React app...
Build complete: .../react-web/dist
Uploaded N files to s3://ubuntu-core-gg-demo-dashboard/
Created cache invalidation: ...

============================================================
Dashboard deployed!
URL: https://d1234abcdef.cloudfront.net
============================================================
```

- [ ] **Step 3: Re-run to verify idempotency**

Run: `python3 setup_aws_resources.py --stage hosting --region eu-west-1`
Expected: Same URL printed, uses "already exists" paths, no errors or duplicates.

- [ ] **Step 4: Access the URL in a browser**

Wait 5-10 minutes for initial distribution deployment, then visit the printed CloudFront URL.
Expected: React app login page loads over HTTPS.

---

## Notes

- The `CachePolicyId` value `658327ea-f89d-4fab-a63d-7e88639e58f6` is the AWS managed `CachingOptimized` policy ID — it's a fixed constant across all AWS accounts.
- The `ForwardedValues: None` field is required in the API call when using a `CachePolicyId` — it tells CloudFront to use the cache policy instead of legacy forwarded values configuration. If the boto3 version rejects `None`, remove the key entirely.
- The distribution uses `PriceClass_100` (US, Canada, Europe, Israel) which is the cheapest option and sufficient for a demo.
