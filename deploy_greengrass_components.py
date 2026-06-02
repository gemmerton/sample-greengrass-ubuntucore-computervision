#!/usr/bin/env python3
"""
AWS Greengrass Component Deployment Script

This script automates the creation and deployment of Greengrass components
from a local folder structure to AWS IoT Greengrass.

Supports three stages:
- create: Upload artifacts and create components in AWS
- deploy: Create deployment to IoT Thing (components must exist)
- full: Both create and deploy in one operation
"""

import os
import sys
import json
import yaml
import boto3
import argparse
from pathlib import Path
from botocore.exceptions import ClientError
from setup_aws_resources import AWSResourcesSetup

class GreengrassDeployer:
    def __init__(self, s3_bucket, aws_region='us-east-1'):
        self.s3_bucket = s3_bucket
        self.aws_region = aws_region
        
        # Initialize AWS clients
        self.s3_client = boto3.client('s3', region_name=aws_region)
        self.greengrass_client = boto3.client('greengrassv2', region_name=aws_region)
        self.iot_client = boto3.client('iot', region_name=aws_region)
        self.sts_client = boto3.client('sts', region_name=aws_region)
        
        # Get AWS account ID
        self.account_id = self.sts_client.get_caller_identity()['Account']
        
        self.components_dir = Path('greengrass-components')
        self.recipes_dir = self.components_dir / 'recipes'
        self.artifacts_dir = self.components_dir / 'artifacts'

    def validate_structure(self):
        """Validate the expected folder structure exists."""
        if not self.components_dir.exists():
            raise FileNotFoundError(f"Components directory not found: {self.components_dir}")
        if not self.recipes_dir.exists():
            raise FileNotFoundError(f"Recipes directory not found: {self.recipes_dir}")
        if not self.artifacts_dir.exists():
            raise FileNotFoundError(f"Artifacts directory not found: {self.artifacts_dir}")

    def upload_artifacts_to_s3(self, component_name, local_version, s3_version=None):
        """Upload component artifacts to S3.
        
        Args:
            component_name: The component name (used for local path and S3 prefix)
            local_version: The version used in the local artifacts directory structure
            s3_version: The version used in the S3 key path (defaults to local_version)
        """
        if s3_version is None:
            s3_version = local_version

        artifact_path = self.artifacts_dir / component_name / local_version
        if not artifact_path.exists():
            print(f"No artifacts found for {component_name} v{local_version}")
            return {}

        uploaded_artifacts = {}
        s3_prefix = f"greengrass-components/{component_name}/{s3_version}/"

        for artifact_file in artifact_path.iterdir():
            if artifact_file.is_file():
                s3_key = s3_prefix + artifact_file.name
                
                try:
                    self.s3_client.upload_file(
                        str(artifact_file),
                        self.s3_bucket,
                        s3_key
                    )
                    s3_uri = f"s3://{self.s3_bucket}/{s3_key}"
                    uploaded_artifacts[artifact_file.name] = s3_uri
                    print(f"Uploaded {artifact_file.name} to {s3_uri}")
                except ClientError as e:
                    print(f"Failed to upload {artifact_file.name}: {e}")
                    raise

        return uploaded_artifacts

    def update_recipe_with_s3_uris(self, recipe_data, uploaded_artifacts):
        """Update recipe with S3 URIs for artifacts."""
        if 'Manifests' in recipe_data:
            for manifest in recipe_data['Manifests']:
                if 'Artifacts' in manifest:
                    for artifact in manifest['Artifacts']:
                        artifact_name = artifact['Uri']
                        if artifact_name in uploaded_artifacts:
                            artifact['Uri'] = uploaded_artifacts[artifact_name]
        return recipe_data

    def get_next_version(self, component_name, base_version):
        """Get the next available version for a component by incrementing the patch number.
        
        Queries existing versions and returns a version higher than any that already exist.
        For example, if 1.0.0 and 1.0.1 exist, returns 1.0.2.
        """
        try:
            response = self.greengrass_client.list_component_versions(
                arn=f"arn:aws:greengrass:{self.aws_region}:{self.account_id}:components:{component_name}"
            )
            existing_versions = [v['componentVersion'] for v in response.get('componentVersions', [])]
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                # Component doesn't exist yet, use base version
                return base_version
            raise

        if not existing_versions or base_version not in existing_versions:
            return base_version

        # Parse base version and find the highest patch for this major.minor
        parts = base_version.split('.')
        major, minor = parts[0], parts[1]
        prefix = f"{major}.{minor}."

        max_patch = -1
        for v in existing_versions:
            if v.startswith(prefix):
                try:
                    patch = int(v.split('.')[2])
                    max_patch = max(max_patch, patch)
                except (IndexError, ValueError):
                    continue

        next_patch = max_patch + 1 if max_patch >= 0 else 0
        return f"{major}.{minor}.{next_patch}"

    def delete_component_version(self, component_name, component_version):
        """Delete a specific component version."""
        try:
            self.greengrass_client.delete_component(
                arn=f"arn:aws:greengrass:{self.aws_region}:{self.account_id}:components:{component_name}:versions:{component_version}"
            )
            print(f"Deleted component: {component_name} v{component_version}")
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print(f"Component {component_name} v{component_version} not found")
                return False
            else:
                print(f"Failed to delete component {component_name}: {e}")
                return False

    def cancel_deployment(self, thing_name):
        """Cancel active deployments for a thing."""
        try:
            target_arn = f"arn:aws:iot:{self.aws_region}:{self.account_id}:thing/{thing_name}"
            response = self.greengrass_client.list_deployments(
                targetArn=target_arn,
                maxResults=10
            )
            
            for deployment in response.get('deployments', []):
                deployment_id = deployment['deploymentId']
                status = deployment['deploymentStatus']
                
                if status in ['ACTIVE', 'IN_PROGRESS']:
                    try:
                        self.greengrass_client.cancel_deployment(
                            deploymentId=deployment_id
                        )
                        print(f"Cancelled deployment: {deployment_id}")
                    except ClientError as e:
                        print(f"Could not cancel deployment {deployment_id}: {e}")
        except ClientError as e:
            print(f"Error listing deployments: {e}")

    def create_component(self, recipe_file):
        """Create a Greengrass component from a recipe file.

        Auto-increments the patch version on each deploy so the device always
        picks up new artifacts and the console shows version progression.
        """
        with open(recipe_file, 'r', encoding='utf-8') as f:
            recipe_data = yaml.safe_load(f)

        component_name = recipe_data['ComponentName']
        base_version = recipe_data['ComponentVersion']

        # Always auto-increment patch version to ensure the device picks up new artifacts
        component_version = self.get_next_version(component_name, base_version)
        if component_version != base_version:
            print(f"Auto-incrementing version: {base_version} -> {component_version}")
        recipe_data['ComponentVersion'] = component_version

        print(f"Processing component: {component_name} v{component_version}")

        # Upload artifacts to S3 (use base version for local path, new version for S3 key)
        uploaded_artifacts = self.upload_artifacts_to_s3(component_name, base_version, component_version)
        
        # Update recipe with S3 URIs
        recipe_data = self.update_recipe_with_s3_uris(recipe_data, uploaded_artifacts)
        
        # Update S3 bucket configuration for InferenceHandlerCore
        if component_name == 'com.example.InferenceHandlerCore':
            if 'ComponentConfiguration' in recipe_data and 'DefaultConfiguration' in recipe_data['ComponentConfiguration']:
                recipe_data['ComponentConfiguration']['DefaultConfiguration']['S3BucketName'] = self.s3_bucket
                print(f"Updated S3BucketName to: {self.s3_bucket}")

        # Collect DefaultConfiguration values to propagate via
        # configurationUpdate.merge at deploy time. This includes accessControl
        # so that permission changes in recipes take effect on devices that
        # already have an older config in config.tlog.
        default_config = {}
        cfg = recipe_data.get('ComponentConfiguration', {}).get('DefaultConfiguration', {})
        for k, v in cfg.items():
            default_config[k] = v

        # Create component
        try:
            response = self.greengrass_client.create_component_version(
                inlineRecipe=yaml.dump(recipe_data).encode('utf-8')
            )
            print(f"Created component: {component_name} v{component_version}")
            return {
                'componentName': component_name,
                'componentVersion': component_version,
                'arn': response['arn'],
                'defaultConfig': default_config,
            }
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConflictException':
                print(f"Component {component_name} v{component_version} already exists (unexpected)")
                return {
                    'componentName': component_name,
                    'componentVersion': component_version,
                    'arn': f"arn:aws:greengrass:{self.aws_region}:{self.account_id}:components:{component_name}:versions:{component_version}",
                    'defaultConfig': default_config,
                }
            else:
                print(f"Failed to create component {component_name}: {e}")
                raise

    def create_all_components(self):
        """Create all components from recipe files."""
        components = []

        for recipe_file in self.recipes_dir.glob('*.yaml'):
            component = self.create_component(recipe_file)
            components.append(component)

        return components

    def _get_latest_public_component_version(self, component_name):
        """Return the latest version of a public AWS Greengrass component."""
        arn = f"arn:aws:greengrass:{self.aws_region}:aws:components:{component_name}"
        try:
            response = self.greengrass_client.list_component_versions(arn=arn)
            versions = [v['componentVersion'] for v in response.get('componentVersions', [])]
            if versions:
                def _ver_key(v):
                    try:
                        return tuple(int(x) for x in v.split('.'))
                    except ValueError:
                        return (0, 0, 0)
                return max(versions, key=_ver_key)
        except ClientError as e:
            print(f"Warning: could not resolve latest version for {component_name}: {e}")
        return None

    def create_deployment(self, thing_name, components):
        """Create a Greengrass deployment to the specified IoT Thing."""
        deployment_name = f"deployment-{thing_name}"

        # Build component configuration from the supplied custom components.
        # We merge the recipe DefaultConfiguration (minus accessControl) so that
        # changes to those values propagate to devices that already have an older
        # value in config.tlog. A root reset:[''] is deliberately avoided — it
        # wipes lifecycle scripts from the config tree before the recipe content
        # is restored, leaving GenericExternalService with no Run script.
        component_config = {}
        for component in components:
            entry = {'componentVersion': component['componentVersion']}
            default_config = component.get('defaultConfig', {})
            if default_config:
                entry['configurationUpdate'] = {
                    'merge': json.dumps(default_config)
                }
            component_config[component['componentName']] = entry

        # Include AWS-managed system components required for credential vending.
        system_components = [
            'aws.greengrass.TokenExchangeService',
        ]
        for name in system_components:
            if name not in component_config:
                version = self._get_latest_public_component_version(name)
                if version:
                    component_config[name] = {'componentVersion': version}
                    print(f"Including system component {name} v{version}")
                else:
                    print(f"Warning: skipping {name} — could not resolve version")

        try:
            response = self.greengrass_client.create_deployment(
                targetArn=f"arn:aws:iot:{self.aws_region}:{self.account_id}:thing/{thing_name}",
                deploymentName=deployment_name,
                components=component_config,
                deploymentPolicies={
                    'failureHandlingPolicy': 'ROLLBACK',
                    'componentUpdatePolicy': {
                        'timeoutInSeconds': 300,
                        'action': 'NOTIFY_COMPONENTS'
                    }
                }
            )
            
            deployment_id = response['deploymentId']
            print(f"Created deployment {deployment_id} for thing {thing_name}")
            return deployment_id
            
        except ClientError as e:
            print(f"Failed to create deployment: {e}")
            raise

    def create_components_only(self):
        """Create components without deployment."""
        print(f"Creating Greengrass components...")
        print(f"Using S3 bucket: {self.s3_bucket}")
        print(f"AWS Region: {self.aws_region}")

        # Validate structure
        self.validate_structure()

        # Create all components
        components = self.create_all_components()
        
        print(f"\nComponents created successfully!")
        print(f"Total components: {len(components)}")
        for component in components:
            print(f"  - {component['componentName']} v{component['componentVersion']}")
        
        return components

    def ensure_device_shadows(self, thing_name):
        """Ensure required named shadows exist for the device.

        Creates model-config, kvs-config, and inference-config shadows with
        default desired state if they don't already exist. Existing shadows
        are left untouched.
        """
        iot_data = boto3.client('iot-data', region_name=self.aws_region)

        shadows = {
            'model-config': {
                'state': {'desired': {
                    'models': {
                        'faster-rcnn': {'source': 'snap', 'type': 'cv'},
                        'person-detection': {'source': 'snap', 'type': 'cv'},
                        'yolov8s': {'source': 'snap', 'comp_s3_uri': 's3://gg-ge-test/components/ovms-engine+model-yolov8s.comp', 'type': 'cv'},
                    },
                    'inference_interval': 1,
                    'confidence_threshold': 0.4,
                }}
            },
            'kvs-config': {
                'state': {'desired': {
                    'stream_name': 'ge-demo-stream',
                    'frame_rate': 15,
                    'resolution': '640x480',
                    'streaming_enabled': True,
                    'staleness_window_seconds': 30.0,
                    'snapshot_interval_seconds': 1,
                }}
            },
            'inference-config': {
                'state': {'desired': {
                    'confidence_threshold': 0.4,
                }}
            },
            'vlm-config': {
                'state': {'desired': {
                    'models': {
                        'gemma3': {'source': 'snap', 'channel': 'stable'},
                        'qwen-vl': {'source': 'snap', 'channel': 'beta'},
                        'internvl2': {
                            'source': 's3-snap',
                            's3_uri': 's3://gg-ge-test/vlm-snaps/internvl2.snap',
                            'components_s3': {
                                'openvino-model-server': 's3://gg-ge-test/vlm-snaps/internvl2+openvino-model-server.comp',
                                'model-internvl2-4b-ov-int4': 's3://gg-ge-test/vlm-snaps/internvl2+model-internvl2-4b-ov-int4.comp',
                            },
                        },
                    },
                    'active_model': 'qwen-vl',
                    'vlm_config': {
                        'system_prompt': 'You are a workplace safety analyst. Analyse the image and return a JSON object with: risk_level (HIGH/MEDIUM/LOW/NONE), summary (one sentence), and risks (array of {description, severity, category}). Only return the JSON object, no other text.',
                        'user_prompt': 'Assess workplace safety risks visible in this scene.',
                        'inference_interval': 15,
                        'max_tokens': 256,
                    },
                }}
            },
        }

        for shadow_name, payload in shadows.items():
            try:
                iot_data.get_thing_shadow(thingName=thing_name, shadowName=shadow_name)
                print(f"Shadow '{shadow_name}' already exists")
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    iot_data.update_thing_shadow(
                        thingName=thing_name,
                        shadowName=shadow_name,
                        payload=json.dumps(payload).encode('utf-8'),
                    )
                    print(f"Created shadow '{shadow_name}' with default desired state")
                else:
                    print(f"Warning: could not check shadow '{shadow_name}': {e}")

    def deploy_to_thing(self, thing_name):
        """Deploy existing components to IoT Thing."""
        print(f"Creating deployment to IoT Thing: {thing_name}")
        print(f"AWS Region: {self.aws_region}")

        if self.s3_bucket == 'dummy':
            print("Warning: S3 bucket not specified for deployment. Components may not have correct S3 configuration.")

        # Ensure device shadows exist before deploying
        self.ensure_device_shadows(thing_name)

        # Get existing components from recipes
        components = self.get_components_from_recipes()

        # Create deployment
        deployment_id = self.create_deployment(thing_name, components)

        print(f"\nDeployment created successfully!")
        print(f"Deployment ID: {deployment_id}")
        print(f"Components deployed: {len(components)}")
        for component in components:
            print(f"  - {component['componentName']} v{component['componentVersion']}")

        return deployment_id

    def get_components_from_recipes(self):
        """Get component information from recipe files, using the latest available version."""
        components = []

        for recipe_file in self.recipes_dir.glob('*.yaml'):
            with open(recipe_file, 'r', encoding='utf-8') as f:
                recipe_data = yaml.safe_load(f)

            component_name = recipe_data['ComponentName']
            base_version = recipe_data['ComponentVersion']

            # Find the latest version that exists in the cloud
            component_version = self._get_latest_version(component_name, base_version)

            cfg = recipe_data.get('ComponentConfiguration', {}).get('DefaultConfiguration', {})
            default_config = {k: v for k, v in cfg.items() if k != 'accessControl'}

            components.append({
                'componentName': component_name,
                'componentVersion': component_version,
                'arn': f"arn:aws:greengrass:{self.aws_region}:{self.account_id}:components:{component_name}:versions:{component_version}",
                'defaultConfig': default_config,
            })

        return components

    def _get_latest_version(self, component_name, base_version):
        """Get the latest existing version for a component, falling back to base_version."""
        try:
            response = self.greengrass_client.list_component_versions(
                arn=f"arn:aws:greengrass:{self.aws_region}:{self.account_id}:components:{component_name}"
            )
            existing_versions = [v['componentVersion'] for v in response.get('componentVersions', [])]
        except ClientError:
            return base_version

        if not existing_versions:
            return base_version

        # Find the highest version with the same major.minor
        parts = base_version.split('.')
        major, minor = parts[0], parts[1]
        prefix = f"{major}.{minor}."

        matching = [v for v in existing_versions if v.startswith(prefix)]
        if not matching:
            return base_version

        # Sort by patch number descending
        matching.sort(key=lambda v: int(v.split('.')[2]), reverse=True)
        return matching[0]

    def deploy_full(self, thing_name):
        """Full deployment: create components and deploy to thing."""
        print(f"Starting full deployment to IoT Thing: {thing_name}")
        print(f"Using S3 bucket: {self.s3_bucket}")
        print(f"AWS Region: {self.aws_region}")

        # Ensure device shadows exist before deploying
        self.ensure_device_shadows(thing_name)

        # Validate structure
        self.validate_structure()

        # Create all components
        components = self.create_all_components()

        # Create deployment
        deployment_id = self.create_deployment(thing_name, components)

        print(f"\nFull deployment completed successfully!")
        print(f"Deployment ID: {deployment_id}")
        print(f"Components deployed: {len(components)}")
        for component in components:
            print(f"  - {component['componentName']} v{component['componentVersion']}")

def get_user_input(prompt, required=True):
    """Get user input with optional validation."""
    while True:
        value = input(prompt).strip()
        if value or not required:
            return value
        print("This field is required. Please enter a value.")

def main():
    parser = argparse.ArgumentParser(description='Deploy Greengrass components to AWS')
    parser.add_argument('--stage', choices=['create', 'deploy', 'full', 'setup'],
                       help='Deployment stage: create (components only), deploy (to thing), full (both), or setup (AWS resources)')
    parser.add_argument('--thing-name', help='IoT Thing name')
    parser.add_argument('--s3-bucket', help='S3 bucket for storing artifacts')
    parser.add_argument('--region', help='AWS region')
    args = parser.parse_args()
    
    # Get stage if not provided
    stage = args.stage
    if not stage:
        print("\nSelect deployment stage:")
        print("1) create - Upload artifacts and create components")
        print("2) deploy - Deploy to IoT Thing")
        print("3) full - Both create and deploy")
        print("4) setup - Setup AWS resources for React dashboard")
        choice = get_user_input("Enter choice (1-4): ")
        stage_map = {'1': 'create', '2': 'deploy', '3': 'full', '4': 'setup'}
        stage = stage_map.get(choice)
        if not stage:
            print("Invalid choice")
            sys.exit(1)
    
    # Get required parameters based on stage
    s3_bucket = args.s3_bucket
    thing_name = args.thing_name
    region = args.region or 'us-east-1'
    
    if stage in ['create', 'full'] and not s3_bucket:
        s3_bucket = get_user_input("Enter S3 bucket name: ")
    
    if stage in ['deploy', 'full'] and not thing_name:
        thing_name = get_user_input("Enter IoT Thing name: ")
    
    if not args.region:
        region_input = get_user_input("Enter AWS region [us-east-1]: ", required=False)
        region = region_input or 'us-east-1'
    
    try:
        deployer = GreengrassDeployer(s3_bucket or 'dummy', region)
        
        if stage == 'create':
            deployer.create_components_only()
        elif stage == 'deploy':
            deployer.deploy_to_thing(thing_name)
        elif stage == 'full':
            deployer.deploy_full(thing_name)
        elif stage == 'setup':
            setup = AWSResourcesSetup(region, 'ubuntu-core-gg-demo')
            setup.setup_all(s3_bucket)
            
    except Exception as e:
        print(f"Operation failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()