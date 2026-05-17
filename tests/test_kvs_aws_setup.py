import sys, os, json
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from setup_aws_resources import AWSResourcesSetup

def make_setup():
    # Bypass __init__ to avoid real boto3 calls; inject mock clients directly
    s = AWSResourcesSetup.__new__(AWSResourcesSetup)
    s.aws_region = "us-east-1"
    s.project_name = "test-project"
    s.account_id = "123456789012"
    s.kvs = MagicMock()
    s.iam = MagicMock()
    return s

def test_create_kvs_stream_uses_24h_retention():
    s = make_setup()
    s.kvs.describe_stream.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException"}}, "DescribeStream")
    s.kvs.create_stream.return_value = {
        "StreamARN": "arn:aws:kinesisvideo:us-east-1:123456789012:stream/test/0"}
    s.create_kvs_stream("test-stream")
    call_kwargs = s.kvs.create_stream.call_args.kwargs
    assert call_kwargs["DataRetentionInHours"] == 24

def test_create_kvs_stream_skips_if_already_exists():
    s = make_setup()
    s.kvs.describe_stream.return_value = {
        "StreamInfo": {"StreamARN": "arn:existing"}}
    s.create_kvs_stream("test-stream")
    s.kvs.create_stream.assert_not_called()

def test_attach_kvs_producer_policy_grants_put_media():
    s = make_setup()
    stream_arn = "arn:aws:kinesisvideo:us-east-1:123456789012:stream/s/0"
    s.iam.list_attached_role_policies.return_value = {"AttachedPolicies": []}
    s.iam.create_policy.return_value = {"Policy": {"Arn": "arn:policy"}}
    s.attach_kvs_producer_policy("my-role", stream_arn)
    policy_doc = json.loads(
        s.iam.create_policy.call_args.kwargs["PolicyDocument"])
    actions = policy_doc["Statement"][0]["Action"]
    assert "kinesisvideo:PutMedia" in actions
    assert "kinesisvideo:CreateStream" in actions
    assert "kinesisvideo:DescribeStream" in actions
    assert "kinesisvideo:GetDataEndpoint" in actions

def test_attach_kvs_producer_policy_scoped_to_stream_arn():
    s = make_setup()
    stream_arn = "arn:aws:kinesisvideo:us-east-1:123456789012:stream/s/0"
    s.iam.list_attached_role_policies.return_value = {"AttachedPolicies": []}
    s.iam.create_policy.return_value = {"Policy": {"Arn": "arn:policy"}}
    s.attach_kvs_producer_policy("my-role", stream_arn)
    policy_doc = json.loads(
        s.iam.create_policy.call_args.kwargs["PolicyDocument"])
    assert policy_doc["Statement"][0]["Resource"] == stream_arn

def test_attach_kvs_viewer_policy_grants_get_hls():
    s = make_setup()
    stream_arn = "arn:aws:kinesisvideo:us-east-1:123456789012:stream/s/0"
    s.iam.list_attached_role_policies.return_value = {"AttachedPolicies": []}
    s.iam.create_policy.return_value = {"Policy": {"Arn": "arn:policy"}}
    s.attach_kvs_viewer_policy("cognito-role", stream_arn)
    policy_doc = json.loads(
        s.iam.create_policy.call_args.kwargs["PolicyDocument"])
    actions = policy_doc["Statement"][0]["Action"]
    assert "kinesisvideo:GetHLSStreamingSessionURL" in actions
    assert "kinesisvideo:GetDataEndpoint" in actions
    assert "kinesisvideo:DescribeStream" in actions
