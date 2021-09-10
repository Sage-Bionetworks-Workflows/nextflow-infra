#!/usr/bin/env python3

import argparse
import json
import os
import re
from typing import NewType, List, Sequence, Dict

import boto3
import requests  # type: ignore
import yaml  # type: ignore


REGION = "us-east-1"

ROLE_MAPPING = {
    "owners": "owner",
    "admins": "admin",
    "maintainers": "maintain",
    "launchers": "launch",
    "viewers": "view",
}

Email = NewType("Email", str)


class TowerConfigurator:
    def __init__(self, projects: Dict[str, dict], org_name: str, vpc_stack_name: str):
        """Generate TowerConfigurator instance

        The descriptions below for the user types were copied
        from the Nextflow Tower interface.

        Args:
            stack_name (str): CloudFormation stack name
            org_name (str): Name of organization in Tower
            vpc_stack_name (str): Name of the VPC CFN stack

        Raises:
            KeyError: The 'NXF_TOWER_TOKEN' environment variable isn't defined
        """
        # Store CLI arguments and constants
        self.region = REGION
        self.projects = projects
        self.org_name = org_name
        self.vpc_stack_name = vpc_stack_name
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
        # Create and populate Tower organization
        org_id = self.create_tower_organization()
        self.populate_tower_organization(org_id)
        # Iterate over the projects
        vpc_stack = self.get_cfn_stack_outputs(self.vpc_stack_name)
        for stack_name in self.projects.keys():
            # Retrieve information from CloudFormation
            project_stack = self.get_cfn_stack_outputs(stack_name)
            # Prepare the organization and project workspace
            ws_id = self.create_tower_workspace(org_id, stack_name)
            self.populate_tower_workspace(org_id, ws_id, stack_name)
            # Create the credentials and compute environment in the workspace
            self.create_tower_compute_env(project_stack, vpc_stack, ws_id)

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

    def get_tower_api_base_url(self) -> str:
        """Infer Nextflow Tower API endpoint from CloudFormation

        Returns:
            str: A full URL for the Tower API endpoint
        """
        stack = self.get_cfn_stack_outputs("nextflow-r53-alias-record")
        hostname = stack["Route53RecordSet"]
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

    def send_tower_request(self, method: str, endpoint: str, **kwargs) -> dict:
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

    def add_organization_member(self, org_id: str, user: Email) -> int:
        """Add user to the organization (if need be) and return member ID

        Args:
            org_id (str): Identifier for the Tower organization
            user (Email): Email address for the user

        Returns:
            int: Member ID for the user in the given organization
        """
        # Attempt to add the user as a member of the given organization
        endpoint = f"/orgs/{org_id}/members"
        data = {"user": user}
        response = self.send_tower_request(
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
            response = self.send_tower_request("GET", endpoint)
            members = response["members"]
            for member in members:
                if member["userName"] == username:
                    member_id = member["memberId"]
                    break
        # Otherwise, just return their new member ID for the organization
        else:
            member_id = response["member"]["memberId"]
        return member_id

    def populate_tower_organization(self, org_id: str) -> Dict[str, dict]:
        """Add all emails from across all projects to the organization

        Args:
            org_id (str): Identifier for the Tower organization

        Returns:
            Dict[str, dict]: Same as self.project, but with member IDs
        """
        member_ids: Dict[str, Dict[str, List[int]]] = dict()
        for stack_name, users in self.projects.items():
            member_ids[stack_name] = dict()
            for user_group, user_list in users.items():
                user_id_list = list()
                for user in user_list:
                    member_id = self.add_organization_member(org_id, user)
                    user_id_list.append(member_id)
                member_ids[stack_name][user_group] = user_id_list
        self.member_ids = member_ids
        return member_ids

    def create_tower_organization(self) -> int:
        """Create (or get existing) Tower organization

        Returns:
            int: Organization ID
        """
        # Check if given org name is already among the existing orgs
        endpoint = "/orgs"
        response = self.send_tower_request("GET", endpoint)
        for org in response["organizations"]:
            if org["fullName"] == self.org_name:
                return org["orgId"]
        # Otherwise, create a new organization
        data = {
            "organization": {
                "name": re.sub(r"[^A-Za-z0-9_-]", "-", self.org_name),
                "fullName": self.org_name,
                "description": None,
                "location": None,
                "website": None,
                "logo": None,
            },
            "logoId": None,
        }
        response = self.send_tower_request("POST", endpoint, json=data)
        return response["organization"]["orgId"]

    def create_tower_workspace(self, org_id: int, stack_name: str) -> int:
        """Create a Tower workspace under an organization

        Args:
            org_id (int): Identifier for the Tower organization
            stack_name (str): CloudFormation stack name

        Returns:
            Tuple[int, int]: A pair of integer IDs correspond
            to the organization and the project workspace
        """
        # Check if the project workspace already exists
        endpoint = f"/orgs/{org_id}/workspaces"
        response = self.send_tower_request("GET", endpoint)
        for workspace in response["workspaces"]:
            if workspace["name"] == stack_name:
                return workspace["id"]
        # Otherwise, create a new project workspace under the organization
        data = {
            "workspace": {
                "name": stack_name,
                "fullName": stack_name,
                "description": None,
                "visibility": "PRIVATE",
            }
        }
        response = self.send_tower_request("POST", endpoint, json=data)
        return response["workspace"]["id"]

    def create_tower_credentials(self, project_stack: dict, ws_id: int) -> int:
        """Create entry for Forge credentials under the given workspace

        Args:
            project_stack (dict): Outputs from the Tower project CFN stack
            ws_id (int): Identifier for the project workspace in Tower

        Returns:
            int: Identifier for the Forge credentials entry
        """
        # Check if Forge credentials have already been created for this project
        endpoint = "/credentials"
        params = {"workspaceId": ws_id}
        stack_name = project_stack["stack_name"]
        response = self.send_tower_request("GET", endpoint, params=params)
        for cred in response["credentials"]:
            if cred["name"] == stack_name:
                assert cred["provider"] == "aws"
                assert cred["deleted"] is None
                return cred["id"]
        # Otherwise, create a new credentials entry for the project
        secret_arn = project_stack["TowerForgeServiceUserAccessKeySecretArn"]
        credentials = self.get_secret_value(secret_arn)
        data = {
            "credentials": {
                "name": stack_name,
                "provider": "aws",
                "keys": {
                    "accessKey": credentials["aws_access_key_id"],
                    "secretKey": credentials["aws_secret_access_key"],
                    "assumeRoleArn": project_stack["TowerForgeServiceRoleArn"],
                },
                "description": f"Credentials for {stack_name}",
            }
        }
        response = self.send_tower_request("POST", endpoint, params=params, json=data)
        return response["credentialsId"]

    def create_tower_compute_env(
        self, project_stack: dict, vpc_stack: dict, ws_id: int
    ) -> str:
        """Create default compute environment under the given workspace

        Args:
            project_stack (dict): Outputs from the Tower project CFN stack
            vpc_stack (dict): Outputs from the Tower VPC CFN stack
            ws_id (int): Identifier for the project workspace in Tower

        Returns:
            str: Identifier for the compute environment
        """
        # Check if compute environment has already been created for this project
        endpoint = "/compute-envs"
        stack_name = project_stack["stack_name"]
        comp_env_name = f"{stack_name} (default)"
        params = {"workspaceId": ws_id}
        response = self.send_tower_request("GET", endpoint, params=params)
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
        credentials_id = self.create_tower_credentials(project_stack, ws_id)
        data = {
            "computeEnv": {
                "name": comp_env_name,
                "platform": "aws-batch",
                "credentialsId": credentials_id,
                "config": {
                    "configMode": "Batch Forge",
                    "region": self.region,
                    "workDir": f"s3://{project_stack['TowerBucket']}/work",
                    "credentials": None,
                    "computeJobRole": project_stack["TowerForgeBatchWorkJobRoleArn"],
                    "headJobRole": project_stack["TowerForgeBatchHeadJobRoleArn"],
                    "headJobCpus": None,
                    "headJobMemoryMb": None,
                    "preRunScript": None,
                    "postRunScript": None,
                    "cliPath": None,
                    "forge": {
                        "vpcId": vpc_stack["VPCId"],
                        "subnets": [
                            vpc_stack["PrivateSubnet"],
                            vpc_stack["PrivateSubnet1"],
                            vpc_stack["PrivateSubnet2"],
                            vpc_stack["PrivateSubnet3"],
                        ],
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
        response = self.send_tower_request("POST", endpoint, params=params, json=data)
        return response["computeEnvId"]

    def add_workspace_participant(self, org_id: str, ws_id: str, member_id: int) -> int:
        """Add user to the workspace (if need be) and return participant ID

        Args:
            org_id (str): Identifier for the Tower organization
            ws_id (str): Identifier for the project workspace in Tower
            member_id (int): Member ID for the user in the given organization

        Returns:
            int: Participant ID for the user in the given workspace
        """
        # Attempt to add the user as a participant of the given workspace
        endpoint = f"/orgs/{org_id}/workspaces/{ws_id}/participants"
        data = {
            "memberId": member_id,
            "teamId": None,
            "userNameOrEmail": None,
        }
        response = self.send_tower_request("PUT", f"{endpoint}/add", json=data)
        # If the user is already a member, you get the following message:
        #   "Already a participant"
        # In this case, look up the participant ID using the member ID
        if "message" in response and response["message"] == "Already a participant":
            response = self.send_tower_request("GET", endpoint)
            for participant in response["participants"]:
                if participant["memberId"] == member_id:
                    participant_id = participant["participantId"]
                    break
        # Otherwise, just return their new participant ID for the workspace
        else:
            participant_id = response["participant"]["participantId"]
        return participant_id

    def set_workspace_role(
        self, org_id: str, ws_id: str, part_id: int, role: str
    ) -> None:
        """Update the participant role in the given workspace

        Args:
            org_id (str): Identifier for the Tower organization
            ws_id (str): Identifier for the project workspace in Tower
            part_id (int): Participant ID for the user in the given workspace
            role (str): 'owner', 'admin', 'maintain', 'launch', or 'view'
        """
        endpoint = f"/orgs/{org_id}/workspaces/{ws_id}/participants/{part_id}/role"
        data = {"role": role}
        self.send_tower_request("PUT", endpoint, json=data)

    def populate_tower_workspace(
        self, org_id: str, ws_id: str, stack_name: str
    ) -> None:
        """Add maintainers and viewers to the organization and workspace

        Args:
            org_id (str): Identifier for the Tower organization
            ws_id (str): Identifier for the project workspace in Tower
            stack_name (str): CloudFormation stack name
        """
        users = self.member_ids[stack_name]
        for user_group, user_list in users.items():
            role = ROLE_MAPPING[user_group]
            for member_id in user_list:
                part_id = self.add_workspace_participant(org_id, ws_id, member_id)
                self.set_workspace_role(org_id, ws_id, part_id, role)


def parse_args() -> argparse.Namespace:
    """Parse and validate command-line arguments

    Returns:
        argparse.Namespace: Validated command-line arguments
    """
    # Parse command-line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("stack_group_dir")
    parser.add_argument("--org_name", "-n", default="Sage Bionetworks")
    parser.add_argument("--vpc_stack_name", "-v", default="nextflow-vpc")
    args = parser.parse_args()
    return args


def load_project_configs(stack_group_dir: str) -> List[dict]:
    """Load all project configuration files from given directory

    Args:
        stack_group_dir (str): Directory containing project configs

    Returns:
        List[dict]: List of parsed YAML files for Tower projects
    """
    # Ignore all Sceptre resolvers
    yaml.add_multi_constructor("!", lambda loader, suffix, node: None)
    # Obtain a list of config files from the given directory
    config_paths = list()
    for dirpath, _, filenames in os.walk(stack_group_dir):
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


def extract_emails_from_arns(arns: Sequence[str]) -> List[str]:
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


def summarize_configs(configs: Sequence[dict]) -> Dict[str, dict]:
    summary = dict()
    for config in configs:
        stack_name = config["stack_name"]
        maintainer_arns = config["parameters"].get("S3ReadWriteAccessArns", [])
        viewer_arns = config["parameters"].get("S3ReadOnlyAccessArns", [])
        maintainers = extract_emails_from_arns(maintainer_arns)
        viewers = extract_emails_from_arns(viewer_arns)
        summary[stack_name] = {"maintainers": maintainers, "viewers": viewers}
    return summary


if __name__ == "__main__":
    args = parse_args()
    configs = load_project_configs(args.stack_group_dir)
    projects = summarize_configs(configs)
    tower = TowerConfigurator(projects, args.org_name, args.vpc_stack_name)
    tower.configure()
