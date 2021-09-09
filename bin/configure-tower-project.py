#!/usr/bin/env python3

import argparse
from typing import NewType, Sequence, Tuple
import json
import os

import boto3
from requests import request, Response


REGION = "us-east-1"

Email = NewType("Email", str)


class TowerConfigurator:
    def __init__(
        self, stack_name: str, maintainers: Sequence[Email], viewers: Sequence[Email]
    ):
        """Generate TowerConfigurator instance

        Args:
            stack_name (str): CloudFormation stack name
            maintainers (Sequence[Email]):
                List of users capable of launching workflows
            viewers (Sequence[Email]):
                List of users capable of monitoring workflow execution

        Raises:
            KeyError: The 'NXF_TOWER_TOKEN' environment variable isn't defined
        """
        # Store CLI arguments and constants
        self.stack_name = stack_name
        self.maintainers = maintainers
        self.viewers = viewers
        self.region = REGION
        # Use AWS_PROFILE or default profile
        self.session = boto3.session.Session()
        # Infer Tower API base URL from Route53 CFN stack
        self.tower_api_base_url = self.get_tower_api_base_url()
        # Retrieve Nextflow token from environment
        try:
            self.tower_token = os.environ["NXF_TOWER_TOKEN"]
        except KeyError as e:
            raise KeyError(
                "The 'NXF_TOWER_TOKEN' environment variable must "
                "be defined with a Nextflow Tower API token."
            ) from e

    def configure(self):
        """Configure the project in Nextflow Tower"""
        # Retrieve information from CloudFormation
        project_stack = self.get_cfn_stack_outputs(self.stack_name)
        vpc_stack = self.get_cfn_stack_outputs("nextflow-vpc")
        # Prepare the Sage organization and project workspace
        org_id, workspace_id = self.create_tower_workspace()
        self.add_workspace_participants(org_id, workspace_id)
        # Create the credentials and compute environment in the workspace
        self.create_tower_compute_env(project_stack, vpc_stack, workspace_id)

    def get_cfn_stack_outputs(self, stack_name: str) -> dict:
        """Retrieve output values for a CloudFormation stack

        Args:
            stack_name (str): CloudFormation stack name

        Returns:
            dict: A mapping between output names and their values
        """
        cfn = self.session.client("cloudformation")
        response = cfn.describe_stacks(StackName=stack_name)
        outputs_raw = response["Stacks"][0]["Outputs"]
        outputs = {p["OutputKey"]: p["OutputValue"] for p in outputs_raw}
        return outputs

    def get_tower_api_base_url(self) -> str:
        """Infer Nextflow Tower API endpoint from CloudFormation

        Returns:
            str: A full URL for the Tower API endpoint
        """
        stack = self.get_cfn_stack_outputs("nextflow-r53-alias-record")
        hostname = stack["ConnectDNSRecord"]
        endpoint = f"https://{hostname}/api"
        return endpoint

    def get_secret_value(self, secret_arn: str) -> dict:
        """Retrieve value for a secret stored in Secrets Manager

        Args:
            secret_arn (str): ARN for Secrets Manager secret

        Returns:
            dict: Decrypted secret value
        """
        secretsmanager = self.session.client("secretsmanager")
        response = secretsmanager.get_secret_value(SecretId=secret_arn)
        secret_value = json.loads(response["SecretString"])
        return secret_value

    def send_tower_request(self, method: str, endpoint: str, **kwargs) -> Response:
        """Make an authenticated HTTP request to the Nextflow Tower API

        Args:
            method (str): An HTTP method (GET, PUT, POST, or DELETE)
            endpoint (str): The API endpoint with the path parameters filled in

        Returns:
            Response: The raw Response object to allow for special handling
        """
        assert method in {"GET", "PUT", "POST", "DELETE"}
        url = self.tower_api_base_url + endpoint
        kwargs["headers"] = {"Authorization": f"Bearer {self.tower_token}"}
        response = request(method, url, **kwargs)
        return response

    def create_tower_organization(self) -> int:
        """Create (or get existing) Tower organization for 'Sage Bionetworks'

        Returns:
            int: Organization ID for 'Sage Bionetworks'
        """
        # Check if 'Sage Bionetworks' is already among the existing orgs
        response = self.send_tower_request("GET", "/orgs").json()
        for org in response["organizations"]:
            if org["name"] == "Sage-Bionetworks":
                return org["orgId"]
        # Otherwise, create a new organization called 'Sage Bionetworks'
        data = {
            "organization": {
                "name": "Sage-Bionetworks",
                "fullName": "Sage Bionetworks",
                "description": None,
                "location": None,
                "website": None,
                "logo": None,
            },
            "logoId": None,
        }
        response = self.send_tower_request("POST", "/orgs", json=data).json()
        return response["organization"]["orgId"]

    def create_tower_workspace(self) -> Tuple[int, int]:
        """Create a Tower workspace under the 'Sage Bionetworks' organization

        Returns:
            Tuple[int, int]: A pair of integer IDs correspond to the
            'Sage Bionetworks' organization and the project workspace
        """
        # Get or create 'Sage Bionetworks' organization
        org_id = self.create_tower_organization()
        # Check if the project workspace already exists
        response = self.send_tower_request("GET", f"/orgs/{org_id}/workspaces").json()
        for workspace in response["workspaces"]:
            if workspace["name"] == self.stack_name:
                return org_id, workspace["id"]
        # Otherwise, create a new project workspace under the organization
        data = {
            "workspace": {
                "name": self.stack_name,
                "fullName": self.stack_name,
                "description": None,
                "visibility": "PRIVATE",
            }
        }
        response = self.send_tower_request(
            "POST", f"/orgs/{org_id}/workspaces", json=data
        ).json()
        return org_id, response["workspace"]["id"]

    def create_tower_credentials(self, project_stack: dict, workspace_id: int) -> int:
        """Create entry for Forge credentials under the given workspace

        Args:
            project_stack (dict):
                Outputs from the Tower project CloudFormation stack
            workspace_id (int): Identifier for the project workspace

        Returns:
            int: Identifier for the Forge credentials entry
        """
        # Check if Forge credentials have already been created for this project
        params = {"workspaceId": workspace_id}
        response = self.send_tower_request("GET", "/credentials", params=params).json()
        for cred in response["credentials"]:
            if cred["name"] == self.stack_name:
                assert cred["provider"] == "aws"
                assert cred["deleted"] is None
                return cred["id"]
        # Otherwise, create a new credentials entry for the project
        secret_arn = project_stack["TowerForgeServiceUserAccessKeySecretArn"]
        credentials = self.get_secret_value(secret_arn)
        data = {
            "credentials": {
                "name": self.stack_name,
                "provider": "aws",
                "keys": {
                    "accessKey": credentials["aws_access_key_id"],
                    "secretKey": credentials["aws_secret_access_key"],
                    "assumeRoleArn": project_stack["TowerForgeServiceRoleArn"],
                },
                "description": f"Credentials for {self.stack_name}",
            }
        }
        response = self.send_tower_request(
            "POST", "/credentials", params=params, json=data
        ).json()
        return response["credentialsId"]

    def create_tower_compute_env(self, project_stack, vpc_stack, workspace_id):
        # Check if compute environment already exist for this stack
        params = {"workspaceId": workspace_id}
        response = self.send_tower_request("GET", "/compute-envs", params=params)
        comp_envs = response.json()["computeEnvs"]
        for comp_env in comp_envs:
            if (
                comp_env["name"] == f"{self.stack_name} (default)"
                and comp_env["platform"] == "aws-batch"
                and (
                    comp_env["status"] == "AVAILABLE"
                    or comp_env["status"] == "CREATING"
                )
            ):
                return comp_env["id"]
        # If not, create the credentials
        creds_id = self.create_tower_credentials(project_stack, workspace_id)
        bucket_name = project_stack["TowerBucket"]
        forge_head_role_arn = project_stack["TowerForgeBatchHeadJobRoleArn"]
        forge_work_role_arn = project_stack["TowerForgeBatchWorkJobRoleArn"]
        vpc_id = vpc_stack["VPCId"]
        subnet_ids = [
            vpc_stack["PrivateSubnet"],
            vpc_stack["PrivateSubnet1"],
            vpc_stack["PrivateSubnet2"],
            vpc_stack["PrivateSubnet3"],
        ]
        data = {
            "computeEnv": {
                "name": f"{self.stack_name} (default)",
                "platform": "aws-batch",
                "credentialsId": creds_id,
                "config": {
                    "configMode": "Batch Forge",
                    "region": self.region,
                    "workDir": f"s3://{bucket_name}/work",
                    "credentials": None,
                    "computeJobRole": forge_work_role_arn,
                    "headJobRole": forge_head_role_arn,
                    "headJobCpus": None,
                    "headJobMemoryMb": None,
                    "preRunScript": None,
                    "postRunScript": None,
                    "cliPath": None,
                    "forge": {
                        "vpcId": vpc_id,
                        "subnets": subnet_ids,
                        "fsxMode": "None",
                        "efsMode": "None",
                        "type": "SPOT",
                        "minCpus": 0,
                        "maxCpus": 100,
                        "gpuEnabled": False,
                        "ebsAutoScale": True,
                        "allowBuckets": [],
                        "disposeOnDeletion": True,
                        "instanceTypes": [],
                        "allocStrategy": None,
                        "ec2KeyPair": None,
                        "imageId": None,
                        "securityGroups": [],
                        "ebsBlockSize": None,
                        "fusionEnabled": False,
                        "efsCreate": False,
                        "bidPercentage": None,
                    },
                },
            }
        }
        response = self.send_tower_request(
            "POST", "/compute-envs", params=params, json=data
        )
        response_data = response.json()
        comp_env_id = response_data["computeEnvId"]
        return comp_env_id

    def add_organization_member(self, org_id, user):
        # Attempt to create new user
        org_add_data = {"user": user}
        response = self.send_tower_request(
            "PUT",
            f"/orgs/{org_id}/members/add",
            json=org_add_data,
        )
        if "message" in response.json():
            message = response.json()["message"]
            assert "already a member" in message
            user_name = message.split("'")[1]
            response = self.send_tower_request("GET", f"/orgs/{org_id}/members")
            members = response.json()["members"]
            for member in members:
                if member["userName"] == user_name:
                    member_id = member["memberId"]
                    return member_id
        else:
            member_id = response.json()["member"]["memberId"]
            return member_id

    def add_workspace_participant(self, org_id, workspace_id, member_id):
        data = {
            "memberId": member_id,
            "teamId": None,
            "userNameOrEmail": None,
        }
        response = self.send_tower_request(
            "PUT",
            f"/orgs/{org_id}/workspaces/{workspace_id}/participants/add",
            json=data,
        )
        if "message" in response.json():
            message = response.json()["message"]
            assert message == "Already a participant"
            response = self.send_tower_request(
                "GET", f"/orgs/{org_id}/workspaces/{workspace_id}/participants"
            )
            participants = response.json()["participants"]
            for participant in participants:
                if participant["memberId"] == member_id:
                    participant_id = participant["participantId"]
                    return participant_id
        else:
            participant_id = response.json()["participant"]["participantId"]
            return participant_id

    def update_workspace_role(self, org_id, workspace_id, part_id, role):
        data = {"role": role}
        self.send_tower_request(
            "PUT",
            f"/orgs/{org_id}/workspaces/{workspace_id}/participants/{part_id}/role",
            json=data,
        )

    def add_workspace_participants(self, org_id, workspace_id):
        for user in self.maintainers + self.viewers:
            member_id = self.add_organization_member(org_id, user)
            part_id = self.add_workspace_participant(org_id, workspace_id, member_id)
            role = "maintain" if user in self.maintainers else "view"
            self.update_workspace_role(org_id, workspace_id, part_id, role)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stack_name", "-s", required=True)
    parser.add_argument(
        "--maintainers",
        "-m",
        nargs="*",
        help="List of users (emails) capable of running workflows",
    )
    parser.add_argument(
        "--viewers",
        "-v",
        nargs="*",
        help="List of users (emails) capable of seeing workflow run states",
    )
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = parse_args()
    tower = TowerConfigurator(args.stack_name, args.maintainers, args.viewers)
    tower.configure()
