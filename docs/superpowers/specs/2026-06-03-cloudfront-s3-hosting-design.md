# CloudFront + S3 Hosted React Dashboard

## Goal

Host the React dashboard as a static site on S3 with CloudFront, using Origin Access Control (OAC) for security. Integrated into the existing `setup_aws_resources.py` script as an idempotent `--stage hosting` option that provisions infrastructure, builds the app, and deploys in one command.

## Architecture

```
User Browser
    │
    ▼ (HTTPS)
CloudFront Distribution (*.cloudfront.net)
    │
    ▼ (OAC-signed request)
S3 Bucket ({project_name}-dashboard)
    [BlockAllPublicAccess = true]
    [Static files: index.html, assets/*, etc.]
```

## Security Model

- **S3 bucket**: All `BlockPublicAccess` settings enabled. No direct access is possible from the internet.
- **CloudFront OAC**: The distribution uses an Origin Access Control that signs requests to S3 using the CloudFront service principal. This is AWS's current recommended approach (replaces legacy OAI).
- **Bucket policy**: Allows `s3:GetObject` only when the request comes from the specific CloudFront distribution ARN:
  ```json
  {
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "cloudfront.amazonaws.com"},
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::{bucket}/*",
      "Condition": {
        "StringEquals": {
          "AWS:SourceArn": "arn:aws:cloudfront::{account}:distribution/{dist_id}"
        }
      }
    }]
  }
  ```
- **TLS**: Viewer protocol policy set to `redirect-to-https`. All traffic is encrypted.
- **Application auth**: Cognito handles user authentication at the app layer — the CloudFront distribution itself is publicly accessible (no signed URLs or WAF needed).

## SPA Routing

CloudFront custom error responses handle client-side routing:
- **403** → `/index.html` with HTTP 200 (S3 returns 403 for missing keys when using OAC)
- **404** → `/index.html` with HTTP 200

This ensures direct navigation to routes like `/dashboard` works without a server.

## CloudFront Distribution Configuration

- **Origin**: S3 bucket regional domain (`{bucket}.s3.{region}.amazonaws.com`)
- **Origin access**: OAC (signing behavior: always sign, origin type: S3)
- **Default root object**: `index.html`
- **Viewer protocol policy**: `redirect-to-https`
- **Cache policy**: `CachingOptimized` (managed policy) for static assets
- **Price class**: `PriceClass_100` (US, Canada, Europe) — sufficient for demo
- **HTTP version**: HTTP/2
- **Tags**: `project:{project_name}` for idempotent lookup

## Idempotency Strategy

Each resource creation is guarded by an existence check:

| Resource | Check | If exists |
|----------|-------|-----------|
| S3 bucket | `head_bucket()` | Skip creation |
| OAC | `list_origin_access_controls()` by name | Reuse ID |
| CloudFront distribution | List distributions, find by tag `project:{project_name}` | Update config if needed |
| Bucket policy | N/A | Always overwrite (PUT is idempotent) |
| Build + sync | N/A | Always runs (ensures latest) |
| Cache invalidation | N/A | Always runs after sync |

Re-running the script is safe — it converges to the desired state without duplicating resources.

## Integration with setup_aws_resources.py

### New method: `setup_hosting()`

Added to the `AWSResourcesSetup` class. Orchestrates:
1. Create/verify S3 bucket (dedicated dashboard bucket, not the component artifact bucket)
2. Create/find OAC
3. Create/find CloudFront distribution
4. Set bucket policy
5. Build React app (`subprocess` call to `npm run build` in `react-web/`)
6. Sync build output to S3 (with correct `Content-Type` headers)
7. Create CloudFront invalidation (`/*`)
8. Print the distribution URL

### New CLI option: `--stage hosting`

```bash
python setup_aws_resources.py --stage hosting --region eu-west-1
```

The `--stage` choices expand from `[create, deploy, full, setup]` to include `hosting`. It can be run standalone or as part of a broader setup.

### New argument: `--hosting-bucket`

Optional. Defaults to `{project_name}-dashboard`. Allows override if needed.

### New boto3 client

`self.cloudfront = boto3.client('cloudfront')` added to `__init__` (CloudFront is a global service, no region needed).

## S3 Sync Logic

The sync uses `s3.put_object()` iterating over the `react-web/dist/` build output (Vite outputs to `dist/`). Content types are mapped by extension:

| Extension | Content-Type |
|-----------|-------------|
| `.html` | `text/html` |
| `.js` | `application/javascript` |
| `.css` | `text/css` |
| `.json` | `application/json` |
| `.svg` | `image/svg+xml` |
| `.png` | `image/png` |
| `.ico` | `image/x-icon` |
| `.woff2` | `font/woff2` |
| `*` (default) | `application/octet-stream` |

Cache headers:
- `index.html`: `Cache-Control: no-cache` (always revalidated)
- All other files: `Cache-Control: max-age=31536000, immutable` (Vite hashes filenames)

## Build Step

```bash
cd react-web && npm run build
```

This runs `tsc && vite build`, producing output in `react-web/dist/`. The script checks for the existence of `react-web/node_modules/` and runs `npm install` if missing.

## Output

On completion, the script prints:
```
Dashboard URL: https://d1234abcdef.cloudfront.net
```

Note: CloudFront distributions take 5-10 minutes to fully deploy on first creation. The URL is functional once the distribution status reaches "Deployed".

## Error Handling

- **Build failure**: Script exits with error, no S3 sync attempted
- **Missing node_modules**: Runs `npm install` automatically before build
- **CloudFront distribution still deploying**: Script prints URL and notes it may take a few minutes to propagate
- **Permission errors**: Clear error message indicating which IAM permissions are needed

## Required IAM Permissions (for the user running the script)

- `s3:CreateBucket`, `s3:PutBucketPolicy`, `s3:PutPublicAccessBlock`, `s3:PutObject`, `s3:HeadBucket`
- `cloudfront:CreateDistribution`, `cloudfront:UpdateDistribution`, `cloudfront:ListDistributions`, `cloudfront:CreateInvalidation`, `cloudfront:ListTagsForResource`, `cloudfront:TagResource`
- `cloudfront:CreateOriginAccessControl`, `cloudfront:ListOriginAccessControls`
