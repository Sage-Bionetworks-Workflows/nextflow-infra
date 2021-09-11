#!/usr/bin/env python3

import json
import os
import re
import sys
from typing import List, Sequence, Dict

import boto3
import requests  # type: ignore
import yaml  # type: ignore


REGION = "us-east-1"
ORG_NAME = "Sage Bionetworks"
R53_STACK_NAME = "nextflow-r53-alias-record"
R53_STACK_OUTPUT = "Route53RecordSet"
VPC_STACK_NAME = "nextflow-vpc"
VPC_STACK_OUTPUT_VID = "VPCId"
VPC_STACK_OUTPUT_SIDS = [
    "PrivateSubnet",
    "PrivateSubnet1",
    "PrivateSubnet2",
    "PrivateSubnet3",
]

ROLE_MAPPING = {
    "owners": "owner",
    "admins": "admin",
    "maintainers": "maintain",
    "launchers": "launch",
    "viewers": "view",
}


def main() -> None:
    projects_dir = sys.argv[1]
    projects = Projects(projects_dir)
    tower = TowerClient()
    org = TowerOrganization(tower, ORG_NAME, projects.users)
    for stack_name, stack_users in projects.users.items():
        TowerWorkspace(org, stack_name, stack_users)


class Projects:
    def __init__(self, config_directory: str) -> None:
        """Create Projects instance

        Args:
            config_directory (str): Directory containing project config files
        """
        self.config_directory = config_directory
        self.configs = self.load_projects()
        self.users = self.extract_users()

    def load_projects(self) -> List[dict]:
        """Load all project configuration files from given directory

        Returns:
            List[dict]: List of parsed YAML files for Tower projects
        """
        # Ignore all Sceptre resolvers
        yaml.add_multi_constructor("!", lambda loader, suffix, node: None)
        # Obtain a list of config files from the given directory
        config_paths = list()
        for dirpath, _, filenames in os.walk(self.config_directory):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if filename.endswith("-project.yaml"):
                    config_paths.append(filepath)
        # Load the tower-project.yaml config files into a list
        configs = list()
        for config_path in config_paths:
            with open(config_path) as config_file:
                config = yaml.load(config_file, Loader=yaml.Loader)
            if config["template_path"] == "tower-project.yaml":
                configs.append(config)
        return configs

    def extract_emails(self, arns: Sequence[str]) -> List[str]:
        """Extract role session names (emails) from assumed-role ARNs

        Args:
            arns (Sequence[str]): List of assumed-role ARNs

        Returns:
            List[str]: List of email from the role session names
        """
        role_arn_regex = re.compile(
            r"arn:aws:sts::(?P<account_id>[0-9]+):assumed-role/(?P<role_name>[^/]+)"
            r"/(?P<session_name>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,})"
        )
        emails = list()
        for arn in arns:
            match = role_arn_regex.fullmatch(arn)
            if match:
                email = match.group("session_name")
                emails.append(email)
        return emails

    def extract_users(self) -> Dict[str, Dict[str, List[str]]]:
        """Extract users from a series of config files

        Returns:
            Dict[str, dict]: Mapping between stacks and users (grouped by role)
        """
        users = dict()
        for config in self.configs:
            stack_name = config["stack_name"]
            maintainer_arns = config["parameters"].get("S3ReadWriteAccessArns", [])
            viewer_arns = config["parameters"].get("S3ReadOnlyAccessArns", [])
            maintainers = self.extract_emails(maintainer_arns)
            viewers = self.extract_emails(viewer_arns)
            users[stack_name] = {"maintainers": maintainers, "viewers": viewers}
        return users


class AwsClient:
    def __init__(self) -> None:
        self.region = REGION
        self.session = boto3.session.Session()

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
        outputs["stack_name"] = stack_name
        return outputs

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


class TowerClient:
    def __init__(self) -> None:
        """Generate NextflowTower instance

        The descriptions below for the user types were copied
        from the Nextflow Tower interface.

        Raises:
            KeyError: The 'NXF_TOWER_TOKEN' environment variable isn't defined
        """
        self.aws = AwsClient()
        self.vpc = self.aws.get_cfn_stack_outputs(VPC_STACK_NAME)
        self.tower_api_base_url = self.get_tower_api_base_url()
        # Retrieve Nextflow token from environment
        try:
            self.tower_token = os.environ["NXF_TOWER_TOKEN"]
        except KeyError as e:
            raise KeyError(
                "The 'NXF_TOWER_TOKEN' environment variable must "
                "be defined with a Nextflow Tower API token."
            ) from e

    def get_valid_name(self, full_name: str) -> str:
        """Generate Tower-friendly name from full name

        Args:
            full_name (str): Full name (with spaces/punctuation)

        Returns:
            str: Name with only alphanumeric, dash and underscore characters
        """
        return re.sub(r"[^A-Za-z0-9_-]", "-", full_name)

    def get_tower_api_base_url(self) -> str:
        """Infer Nextflow Tower API endpoint from CloudFormation

        Returns:
            str: A full URL for the Tower API endpoint
        """
        stack = self.aws.get_cfn_stack_outputs(R53_STACK_NAME)
        hostname = stack[R53_STACK_OUTPUT]
        endpoint = f"https://{hostname}/api"
        return endpoint

    def request(self, method: str, endpoint: str, **kwargs) -> dict:
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
        response = requests.request(method, url, **kwargs)
        try:
            result = response.json()
        except json.decoder.JSONDecodeError:
            result = dict()
        return result


class TowerOrganization:
    def __init__(
        self,
        tower: TowerClient,
        full_name: str,
        users: Dict[str, Dict[str, List[str]]],
    ) -> None:
        self.tower = tower
        self.full_name = full_name
        self.name = self.tower.get_valid_name(full_name)
        self.json = self.create()
        self.id = self.json["orgId"]
        self.users = users
        self.members: Dict[str, dict] = dict()
        self.populate()

    def create(self) -> dict:
        """Get or create Tower organization with the given name

        Returns:
            dict: Organization JSON from API
        """
        # Check if given org name is already among the existing orgs
        endpoint = "/orgs"
        response = self.tower.request("GET", endpoint)
        for org in response["organizations"]:
            if org["fullName"] == self.full_name:
                return org
        # Otherwise, create a new organization
        data = {
            "organization": {
                "name": self.name,
                "fullName": self.full_name,
                "description": None,
                "location": None,
                "website": None,
                "logo": None,
            },
            "logoId": None,
        }
        response = self.tower.request("POST", endpoint, json=data)
        return response["organization"]

    def add_member(self, user: str) -> int:
        """Add user to the organization (if need be) and return member ID

        Args:
            user (str): str address for the user

        Returns:
            int: Member ID for the user in the given organization
        """
        # Attempt to add the user as a member of the given organization
        endpoint = f"/orgs/{self.id}/members"
        data = {"user": user}
        response = self.tower.request(
            "PUT",
            f"{endpoint}/add",
            json=data,
        )
        # If the user is already a member, you get the following message:
        #   "User '<username>' is already a member"
        # This hacky approach is necessary because you need to retrieve the
        # member ID using the username (you can't with the email alone)
        if "message" in response and "already a member" in response["message"]:
            username = response["message"].split("'")[1]
            response = self.tower.request("GET", endpoint)
            members = response["members"]
            for member in members:
                if member["userName"] == username:
                    break
        # Otherwise, just return their new member ID for the organization
        else:
            member = response["member"]
        self.members[user] = member
        return member

    def populate(self) -> None:
        """Add all emails from across all projects to the organization

        Returns:
            Dict[str, dict]: Same as self.project, but with member IDs
        """
        for stack_users in self.users.values():
            for user_list in stack_users.values():
                for user in user_list:
                    self.add_member(user)


class TowerWorkspace:
    def __init__(
        self,
        org: TowerOrganization,
        stack_name: str,
        users: Dict[str, List[str]],
    ) -> None:
        self.org = org
        self.tower = org.tower
        self.stack_name = stack_name
        self.stack = self.tower.aws.get_cfn_stack_outputs(stack_name)
        self.full_name = stack_name
        self.name = self.tower.get_valid_name(stack_name)
        self.json = self.create()
        self.id = self.json["id"]
        self.users = users
        self.participants: Dict[int, dict] = dict()
        self.populate()
        self.create_compute_environment()

    def create(self) -> dict:
        """Create a Tower workspace under an organization

        Returns:
            dict: Workspace JSON from API
        """
        # Check if the project workspace already exists
        endpoint = f"/orgs/{self.org.id}/workspaces"
        response = self.tower.request("GET", endpoint)
        for workspace in response["workspaces"]:
            if workspace["name"] == self.name:
                return workspace
        # Otherwise, create a new project workspace under the organization
        data = {
            "workspace": {
                "name": self.name,
                "fullName": self.full_name,
                "description": None,
                "visibility": "PRIVATE",
            }
        }
        response = self.tower.request("POST", endpoint, json=data)
        return response["workspace"]

    def add_participant(self, member_id: int, role: str) -> int:
        """Add user to the workspace (if need be) and return participant ID

        Args:
            member_id (int): Member ID for the user in the given organization
            role (str): 'owner', 'admin', 'maintain', 'launch', or 'view'

        Returns:
            int: Participant ID for the user in the given workspace
        """
        # Attempt to add the user as a participant of the given workspace
        endpoint = f"/orgs/{self.org.id}/workspaces/{self.id}/participants"
        data = {
            "memberId": member_id,
            "teamId": None,
            "userNameOrstr": None,
        }
        response = self.tower.request("PUT", f"{endpoint}/add", json=data)
        # If the user is already a member, you get the following message:
        #   "Already a participant"
        # In this case, look up the participant ID using the member ID
        if "message" in response and response["message"] == "Already a participant":
            response = self.tower.request("GET", endpoint)
            for participant in response["participants"]:
                if participant["memberId"] == member_id:
                    break
        # Otherwise, just return their new participant ID for the workspace
        else:
            participant = response["participant"]
        self.participants[member_id] = participant
        # Update participant role
        participant_id = participant["participantId"]
        participant["role"] = role
        self.set_participant_role(participant_id, role)
        return participant

    def set_participant_role(self, part_id: int, role: str) -> None:
        """Update the participant role in the given workspace

        Args:
            part_id (int): Participant ID for the user
            role (str): 'owner', 'admin', 'maintain', 'launch', or 'view'
        """
        endpoint = (
            f"/orgs/{self.org.id}/workspaces/{self.id}/participants/{part_id}/role"
        )
        data = {"role": role}
        self.tower.request("PUT", endpoint, json=data)

    def populate(self) -> None:
        """Add maintainers and viewers to the organization and workspace"""
        for role_group, user_list in self.users.items():
            role = ROLE_MAPPING[role_group]
            for user in user_list:
                member_id = self.org.members[user]["memberId"]
                self.add_participant(member_id, role)

    def create_credentials(self) -> int:
        """Create entry for Forge credentials under the given workspace

        Returns:
            int: Identifier for the Forge credentials entry
        """
        # Check if Forge credentials have already been created for this project
        endpoint = "/credentials"
        params = {"workspaceId": self.id}
        response = self.tower.request("GET", endpoint, params=params)
        for cred in response["credentials"]:
            if cred["name"] == self.stack_name:
                assert cred["provider"] == "aws"
                assert cred["deleted"] is None
                return cred["id"]
        # Otherwise, create a new credentials entry for the project
        secret_arn = self.stack["TowerForgeServiceUserAccessKeySecretArn"]
        credentials = self.tower.aws.get_secret_value(secret_arn)
        data = {
            "credentials": {
                "name": self.stack_name,
                "provider": "aws",
                "keys": {
                    "accessKey": credentials["aws_access_key_id"],
                    "secretKey": credentials["aws_secret_access_key"],
                    "assumeRoleArn": self.stack["TowerForgeServiceRoleArn"],
                },
                "description": f"Credentials for {self.stack_name}",
            }
        }
        response = self.tower.request("POST", endpoint, params=params, json=data)
        return response["credentialsId"]

    def create_compute_environment(self) -> str:
        """Create default compute environment under the given workspace

        Returns:
            str: Identifier for the compute environment
        """
        # Check if compute environment has already been created for this project
        endpoint = "/compute-envs"
        comp_env_name = f"{self.stack_name} (default)"
        params = {"workspaceId": self.id}
        response = self.tower.request("GET", endpoint, params=params)
        for comp_env in response["computeEnvs"]:
            if (
                comp_env["name"] == comp_env_name
                and comp_env["platform"] == "aws-batch"
                and (
                    comp_env["status"] == "AVAILABLE"
                    or comp_env["status"] == "CREATING"
                )
            ):
                return comp_env["id"]
        # Otherwise, create a new compute environment for the project
        credentials_id = self.create_credentials()
        data = {
            "computeEnv": {
                "name": comp_env_name,
                "platform": "aws-batch",
                "credentialsId": credentials_id,
                "config": {
                    "configMode": "Batch Forge",
                    "region": self.tower.aws.region,
                    "workDir": f"s3://{self.stack['TowerBucket']}/work",
                    "credentials": None,
                    "computeJobRole": self.stack["TowerForgeBatchWorkJobRoleArn"],
                    "headJobRole": self.stack["TowerForgeBatchHeadJobRoleArn"],
                    "headJobCpus": None,
                    "headJobMemoryMb": None,
                    "preRunScript": None,
                    "postRunScript": None,
                    "cliPath": None,
                    "forge": {
                        "vpcId": self.tower.vpc[VPC_STACK_OUTPUT_VID],
                        "subnets": [self.tower.vpc[o] for o in VPC_STACK_OUTPUT_SIDS],
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
        response = self.tower.request("POST", endpoint, params=params, json=data)
        return response["computeEnvId"]


if __name__ == "__main__":
    main()
