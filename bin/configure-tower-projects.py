#!/usr/bin/env python3

from __future__ import annotations
import argparse
import json
import os
import re
from typing import List, Tuple, Sequence, Dict, Iterator

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


def main() -> None:
    args = parse_args()
    projects = Projects(args.projects_dir)
    if args.dry_run:
        print(
            "The following Tower project configurations were "
            "discovered and confirmed to be valid:\n  -",
            "\n  - ".join(projects.config_paths),
        )
    else:
        tower = TowerClient()
        org = TowerOrganization(tower, projects)
        org.create_workspaces()


class InvalidTowerProject(Exception):
    pass


class Users:
    def __init__(
        self,
        owners: Sequence[str] = [],
        admins: Sequence[str] = [],
        maintainers: Sequence[str] = [],
        launchers: Sequence[str] = [],
        viewers: Sequence[str] = [],
    ):
        """Utility class for storing lists of users and their roles

        All users are stored as emails.

        Args:
            owners (Sequence[str]):
                The users have full permissions on any resources within
                the organization associated with the workspace
            admins (Sequence[str]):
                The users have full permission on the resources associated
                with the workspace. Therefore they can create/modify/delete
                Pipelines, Compute environments, Actions, Credentials. They
                can add/remove users to the workspace, but cannot create a
                new workspace or modify another workspace
            maintainers (Sequence[str]):
                The users can launch pipeline and modify pipeline executions
                (e.g. can change the pipeline launch compute env, parameters,
                pre/post-run scripts, nextflow config) and create new pipeline
                configuration in the Launchpad. The users cannot modify Compute
                env settings and Credentials
            launchers (Sequence[str]):
                The users can launch pipeline executions and modify the
                pipeline input/output parameters. They cannot modify the
                launch configuration and other resources
            viewers (Sequence[str]):
                The users can access to the team resources in read-only mode

        Returns:
            [type]: [description]
        """
        self.owners = owners
        self.admins = admins
        self.maintainers = maintainers
        self.launchers = launchers
        self.viewers = viewers

    def list_users(self) -> Iterator[Tuple[str, str]]:
        """List all users and their Tower roles

        Yields:
            Iterator[Tuple[str, str]]:
                Each element is the user email (str) and Tower role (str)
        """
        role_mapping = {
            "owners": "owner",
            "admins": "admin",
            "maintainers": "maintain",
            "launchers": "launch",
            "viewers": "view",
        }
        for user_group, role in role_mapping.items():
            users = getattr(self, user_group)
            for user in users:
                yield user, role


class Projects:
    def __init__(self, config_directory: str) -> None:
        """Create Projects instance

        Args:
            config_directory (str): Directory containing project config files
        """
        self.config_directory = config_directory
        self.users_per_project = self.extract_users()

    def list_projects(self) -> Iterator[str]:
        """List all project YAML configuration files

        Yields:
            Iterator[str]:
                Each element is a YAML filepath as a str
        """
        # Obtain a list of config files from the given directory
        self.config_paths = list()
        for dirpath, _, filenames in os.walk(self.config_directory):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if filename.endswith("-project.yaml"):
                    self.config_paths.append(filepath)
                    yield filepath

    def validate_config(self, config: Dict) -> None:
        """Validate Tower project configuration

        Args:
            config (Dict): Tower project configuration

        Raises:
            InvalidTowerProject: When the config is invalid
        """
        has_stack_name = "stack_name" in config
        is_valid = (
            has_stack_name
            and "template_path" in config
            and config["template_path"] == "tower-project.yaml"
            and "parameters" in config
            and (
                "S3ReadWriteAccessArns" in config["parameters"]
                or "S3ReadOnlyAccessArns" in config["parameters"]
            )
        )
        if not is_valid:
            if has_stack_name:
                stack_name = config["stack_name"]
                raise InvalidTowerProject(f"{stack_name}.yaml is invalid")
            else:
                raise InvalidTowerProject(f"This config is invalid:\n{config}")

    def load_projects(self) -> Iterator[dict]:
        """Load all project configuration files from given directory

        Yields:
            Iterator[dict]:
                Each element is a parsed YAML file as a dict
        """
        # Ignore all Sceptre resolvers
        yaml.add_multi_constructor("!", lambda loader, suffix, node: None)
        # Load the tower-project.yaml config files into a list
        for config_path in self.list_projects():
            with open(config_path) as config_file:
                config = yaml.load(config_file, Loader=yaml.Loader)
                self.validate_config(config)
                yield config

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
            else:
                raise ValueError(
                    f"Listed ARN ({arn}) doesn't follow expected format: "
                    "'arn:aws:sts::<account_id>:<role_name>:<email>'"
                )
        return emails

    def extract_users(self) -> Dict[str, Users]:
        """Extract users from a series of config files

        Returns:
            Dict[str, Users]:
                Mapping between projects/stacks and users
        """
        users_per_project = dict()
        for config in self.load_projects():
            stack_name = config["stack_name"]
            maintainer_arns = config["parameters"].get("S3ReadWriteAccessArns", [])
            viewer_arns = config["parameters"].get("S3ReadOnlyAccessArns", [])
            maintainers = self.extract_emails(maintainer_arns)
            viewers = self.extract_emails(viewer_arns)
            users_per_project[stack_name] = Users(
                maintainers=maintainers, viewers=viewers
            )
        return users_per_project


class AwsClient:
    def __init__(self) -> None:
        self.region = REGION
        self.session = boto3.session.Session(region_name=REGION)

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
    def __init__(self, tower_token=None) -> None:
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
            self.tower_token = tower_token or os.environ["NXF_TOWER_TOKEN"]
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


class TowerWorkspace:
    def __init__(
        self,
        org: TowerOrganization,
        stack_name: str,
        users: Users,
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
        self.participants: Dict[str, dict] = dict()
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

    def add_participant(self, user: str, role: str) -> int:
        """Add user to the workspace (if need be) and return participant ID

        Args:
            user (str): Email address for the user
            role (str): 'owner', 'admin', 'maintain', 'launch', or 'view'

        Returns:
            int: Participant ID for the user in the given workspace
        """
        # Attempt to add the user as a participant of the given workspace
        endpoint = f"/orgs/{self.org.id}/workspaces/{self.id}/participants"
        member_id = self.org.members[user]["memberId"]
        data = {
            "memberId": member_id,
            "teamId": None,
            "userNameOrEmail": None,
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
        self.participants[user] = participant
        # Update participant role
        participant_id = participant["participantId"]
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
        for user, role in self.users.list_users():
            self.add_participant(user, role)

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
                        "maxCpus": 500,
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


class TowerOrganization:
    def __init__(
        self,
        tower: TowerClient,
        projects: Projects,
        full_name: str = ORG_NAME,
    ) -> None:
        """Create Tower organization helper instance

        Args:
            tower (TowerClient): Nextflow Tower client
            projects (Projects): List of projects and their users
            full_name (str): (Optional) Full name of organization
        """
        self.tower = tower
        self.full_name = full_name
        self.name = self.tower.get_valid_name(full_name)
        self.json = self.create()
        self.id = self.json["orgId"]
        self.projects = projects
        self.users_per_project = projects.users_per_project
        self.members: Dict[str, dict] = dict()
        self.populate()
        self.workspaces: Dict[str, TowerWorkspace] = dict()

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

    def add_member(self, user: str) -> dict:
        """Add user to the organization (if need be) and return member ID

        Args:
            user (str): Email address for the user

        Returns:
            dict: Tower definition of a organization member
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
        for project_users in self.users_per_project.values():
            for user, _ in project_users.list_users():
                self.add_member(user)

    def list_projects(self) -> Iterator[Tuple[str, Users]]:
        """Iterate over all projects and their users

        Yields:
            Iterator[Tuple[str, Users]]:
                Each element is the project name and its users
        """
        for project, project_users in self.users_per_project.items():
            yield project, project_users

    def create_workspaces(self) -> Dict[str, TowerWorkspace]:
        """Create a workspace for each project

        Returns:
            Dict[str, TowerWorkspace]:
                Mapping of project names and their corresponding workspaces
        """
        for name, users in self.list_projects():
            ws = TowerWorkspace(self, name, users)
            self.workspaces[name] = ws
        return self.workspaces


def parse_args() -> argparse.Namespace:
    """Parse and validate command-line arguments

    Returns:
        argparse.Namespace: Parsed command-line arguments
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("projects_dir")
    parser.add_argument("--dry_run", "-n", action="store_true")
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    main()
