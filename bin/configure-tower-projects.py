#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import defaultdict
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

import boto3  # type: ignore
import yaml  # type: ignore
from sagetasks.nextflowtower.client import TowerClient  # type: ignore

# Increment this version when updating compute environments
CE_VERSION = "v12"

REGION = "us-east-1"
ORG_NAME = "Sage Bionetworks"
VPC_STACK_NAME = "nextflow-vpc"
VPC_STACK_OUTPUT_VID = "VPCId"
VPC_STACK_OUTPUT_SIDS = [
    "PrivateSubnet",
    "PrivateSubnet1",
    "PrivateSubnet2",
    "PrivateSubnet3",
]

# Instruct black code formatter to not list one instance type per line
# fmt: off

# Listing all x86-64 (no Graviton) C/M/R-family (no GPU) instance types
# Limiting to 32 vCPUs (8xlarge) for incremental scaling (max $2/hr)
# Avoiding costly subtypes (e.g., r5b, r5n, r5d) until we benchmark them
NONGPU_EC2_INSTANCE_TYPES = (
    # large instance (2 vCPUs)
    "c6a.large", "c5a.large", "c6i.large", "m5a.large", "m6a.large",
    "m6i.large", "r5a.large", "r6a.large", "r6i.large",
    # xlarge instance (4 vCPUs)
    "c6a.xlarge", "c5a.xlarge", "c6i.xlarge", "m5a.xlarge", "m6a.xlarge",
    "m6i.xlarge", "r5a.xlarge", "r6a.xlarge", "r6i.xlarge",
    # 2xlarge instance (8 vCPUs)
    "c6a.2xlarge", "c5a.2xlarge", "c6i.2xlarge", "m5a.2xlarge", "m6a.2xlarge",
    "m6i.2xlarge", "r5a.2xlarge", "r6a.2xlarge", "r6i.2xlarge",
    # 4xlarge instance (16 vCPUs)
    "c6a.4xlarge", "c5a.4xlarge", "c6i.4xlarge", "m5a.4xlarge", "m6a.4xlarge",
    "m6i.4xlarge", "r5a.4xlarge", "r6a.4xlarge", "r6i.4xlarge",
    # 8xlarge instance (32 vCPUs)
    "c6a.8xlarge", "c5a.8xlarge", "c6i.8xlarge", "m5a.8xlarge", "m6a.8xlarge",
    "m6i.8xlarge", "r5a.8xlarge", "r6a.8xlarge", "r6i.8xlarge"
)

ECS_CONFIG = """
ECS_CONTAINER_STOP_TIMEOUT=10m
ECS_CONTAINER_START_TIMEOUT=10m
ECS_CONTAINER_CREATE_TIMEOUT=10m
"""

# fmt: on


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
        tower = TowerClient(debug_mode=args.debug)
        TowerOrganization(tower, projects)


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

    def list_users(self) -> Iterator[Tuple[str, str, str]]:
        """List all users and their Tower roles

        Yields:
            Iterator[Tuple[str, str, str]]:
                Each element is the user email (str), the user group,
                and Tower role (str)
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
                yield user, user_group, role

    def list_teams(self) -> Iterator[Tuple[List[str], str, str]]:
        """List all users grouped by their Tower roles

        Yields:
            Iterator[Tuple[List[str], str, str]]:
                Each element is the list of user emails (List[str]),
                the user group (str), and their Tower role (str)
        """
        teams = defaultdict(list)
        for user, user_group, role in self.list_users():
            teams[(user_group, role)].append(user)
        return ((users, ugrp, role) for (ugrp, role), users in teams.items())


class Projects:
    def __init__(self, config_directory: str) -> None:
        """Create Projects instance

        Args:
            config_directory (str): Directory containing project config files
        """
        self.config_directory = config_directory
        self.users_per_project = self.extract_users()
        self.tags_per_project = self.extract_tags()

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
            and "template" in config
            and config["template"]["path"] == "tower-project.j2"
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
        # Load the tower-project.j2 config files into a list
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
            r".*/(?P<session_name>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,})"
        )
        emails = set()
        for arn in arns:
            match = role_arn_regex.fullmatch(arn)
            if match:
                email = match.group("session_name")
                emails.add(email)
            else:
                print(
                    f"Listed ARN ({arn}) doesn't follow expected format: "
                    "'arn:aws:sts::<account_id>:<role_name>:<email>'"
                )
        return list(emails)

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

    def extract_tags(self) -> Dict[str, Dict[str, str]]:
        """Extract AWS tags for each stack.

        Returns:
            Mapping of projects/stacks and key-value tag pairs.
        """
        tags_per_project = dict()
        for config in self.load_projects():
            stack_name = config["stack_name"]
            stack_tags = config.get("stack_tags", {})
            stack_tags["TowerProject"] = stack_name

            # Only keep the program code for the cost center
            if "CostCenter" in stack_tags:
                _, _, program_code = stack_tags["CostCenter"].rpartition("/")
                stack_tags["CostCenter"] = program_code.strip()

            # Eliminate any invalid characters
            invalid_chars = re.compile(r"[^A-z0-9_-]+")
            original_keys = list(stack_tags)
            for key in original_keys:
                val = stack_tags.pop(key)
                new_key = invalid_chars.sub("_", key)
                new_val = invalid_chars.sub("_", val)
                stack_tags[new_key] = new_val

            tags_per_project[stack_name] = stack_tags
        return tags_per_project


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


class TowerWorkspace:
    def __init__(
        self,
        org: TowerOrganization,
        stack_name: str,
        users: Users = None,
        teams: Dict[int, str] = None,
        tags: Dict[str, str] = None,
    ) -> None:
        self.org = org
        self.tower = org.tower
        self.stack_name = stack_name
        self.stack = self.org.aws.get_cfn_stack_outputs(stack_name)
        self.full_name = stack_name
        self.name = self.tower.get_valid_name(stack_name)
        self.json = self.create()
        self.id = self.json["id"]
        self.users = users
        self.teams = teams
        self.tags = tags or {}
        self.participants: Dict[str, dict] = dict()
        self.populate()
        self.cleanup_compute_environments()
        if self.has_launchers():
            self.create_compute_environment()

    def has_launchers(self) -> bool:
        """Checks whether at least one user is capable of launching a workflow

        Returns:
            bool: Whether there's at least one launcher
        """
        has_launchers = False
        launcher_roles = set(["owner", "admin", "maintain", "launch"])
        if self.users:
            for _, _, role in self.users.list_users():
                if role in launcher_roles:
                    has_launchers = True
                    break
        if self.teams:
            for role in self.teams.values():
                if role in launcher_roles:
                    has_launchers = True
                    break
        return has_launchers

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

    def add_participant(self, role: str, user: str = None, team_id: int = None) -> dict:
        """Add user or team to the workspace (if need be) and return participant ID

        Args:
            role (str): 'owner', 'admin', 'maintain', 'launch', or 'view'
            user (str): Email address for the user. Mutually exclusive with `team_id`.
            team_id (int): Team identifier. Mutually exclusive with `user`.

        Returns:
            dict: Participant info for the user or team in the given workspace
        """
        endpoint = f"/orgs/{self.org.id}/workspaces/{self.id}/participants"
        data = {"memberId": None, "teamId": None, "userNameOrEmail": None}

        if user:
            member_id = self.org.members[user]["memberId"]
            identifier = member_id
            data["memberId"] = identifier
        elif team_id:
            identifier = team_id
            data["teamId"] = identifier
        else:
            message = "Must provide value for exactly one of `user` or `team_id`."
            raise ValueError(message)

        response = self.tower.paged_request("GET", f"{endpoint}")
        matches = [
            participant
            for participant in response
            if participant["teamId"] == identifier
            or participant["memberId"] == identifier
        ]

        if len(matches) == 1:
            participant = matches[0]
        else:
            response = self.tower.request("PUT", f"{endpoint}/add", json=data)
            participant = response["participant"]

        # Update participant role
        participant_id = participant["participantId"]
        self.set_participant_role(participant_id, role)

        self.participants[identifier] = participant
        return participant

    def set_participant_role(self, part_id: int, role: str) -> None:
        """Update the participant role in the given workspace

        Args:
            part_id (int): Participant ID for the user or team
            role (str): 'owner', 'admin', 'maintain', 'launch', or 'view'
        """
        endpoint = (
            f"/orgs/{self.org.id}/workspaces/{self.id}/participants/{part_id}/role"
        )
        data = {"role": role}
        self.tower.request("PUT", endpoint, json=data)

    def remove_participant(self, part_id: int) -> Dict:
        """Remove a participant from a workspace

        Args:
            part_id (int): Participant ID for the user or team
        """
        endpoint = f"/orgs/{self.org.id}/workspaces/{self.id}/participants/{part_id}"
        response = self.tower.request("DELETE", endpoint)
        return response

    def list_participants(self) -> Iterator:
        """List the participants in a workspace"""
        endpoint = f"/orgs/{self.org.id}/workspaces/{self.id}/participants"
        participants = self.tower.paged_request("GET", endpoint)
        return participants

    def list_owner_participant_ids(self) -> Set[int]:
        """List the participant IDs of any workspace owners

        This will include the workspace creator.
        """
        participants = self.list_participants()
        owners = [part for part in participants if part["wspRole"] == "owner"]
        owner_ids = {owner["participantId"] for owner in owners}
        return owner_ids

    def populate(self) -> None:
        """Add maintainers and viewers to the organization and workspace"""
        if self.users:
            owner_ids = self.list_owner_participant_ids()
            verified_ids = set(owner_ids)
            for user, _, role in self.users.list_users():
                # Add expected participants
                part = self.add_participant(role, user=user)
                part_id = part["participantId"]
                verified_ids.add(part_id)
            # Remove unexpected team members
            for part in self.list_participants():
                part_id = part["participantId"]
                if part_id not in verified_ids:
                    self.remove_participant(part_id)
        if self.teams:
            for team_id, role in self.teams.items():
                self.add_participant(role, team_id=team_id)

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
        credentials = self.org.aws.get_secret_value(secret_arn)
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

    def get_resource_label(self, name: str, value: str) -> Optional[int]:
        """Get ID for resource label (if existing).

        Args:
            name: Resource label name.
            value: Resource label value.

        Returns:
            Resource label ID.
        """
        endpoint = "/labels"
        params = {"workspaceId": self.id, "max": 1000, "type": "resource"}
        paged = self.tower.paged_request("GET", endpoint, params=params)
        labels = list(paged)
        if not all(isinstance(label, dict) for label in labels):
            message = f"Labels ({labels}) aren't dictionaries as expected."
            raise ValueError(message)
        matches = [label for label in labels if label["name"] == name]
        matches = [label for label in matches if label["value"] == value]
        if len(matches) == 1:
            return matches[0]["id"]
        else:
            return None

    def create_resource_label(self, name: str, value: str) -> int:
        """Create a resource label (name and value pair).

        Args:
            name: Resource label name.
            value: Resource label value.

        Returns:
            Resource label ID.
        """
        # Check for existing resource label
        label_id = self.get_resource_label(name, value)
        if label_id is not None:
            return label_id

        endpoint = "/labels"
        params = {"workspaceId": self.id}
        data = {"name": name, "value": value, "resource": True}
        response = self.tower.request("POST", endpoint, params=params, json=data)
        return response["id"]

    def cleanup_compute_environments(self):
        """Delete inactive compute environments in the workspace

        This step is necessary to avoid running into AWS' hard limit
        on the number of compute environments, which is 50 per account
        """
        endpoint = "/compute-envs"
        params = {"workspaceId": self.id}
        response = self.tower.request("GET", endpoint, params=params)
        for comp_env in response["computeEnvs"]:
            comp_env_id = comp_env["id"]
            comp_env_name = comp_env["name"]
            if comp_env_name.endswith(CE_VERSION) and self.has_launchers():
                continue
            delete_endpoint = f"{endpoint}/{comp_env_id}"
            response = self.tower.request("DELETE", delete_endpoint, params=params)
            if "message" in response and "has active jobs" in response["message"]:
                print(
                    f"Skipping the deletion of the '{self.name}/{comp_env_name}' "
                    f"compute environment due to active jobs..."
                )

    def generate_compute_environment(self, name: str, model: str) -> dict:
        """Generate request object for creating a compute environment.

        Args:
            name (str): Name of the compute environment
            type (str): Pricing model, either "EC2" (on-demand) or "SPOT"

        Returns:
            dict: [description]
        """
        assert model in {"SPOT", "EC2"}, "Wrong provisioning model"
        credentials_id = self.create_credentials()

        # Retrieve (or create) resource label IDs
        label_ids = []
        for key, value in self.tags.items():
            label_id = self.create_resource_label(key, value)
            label_ids.append(label_id)

        # 'BEST_FIT' ensures that smaller instances are used, which limits the number
        # of jobs per instance. It also ensures that the head job is isolated.
        alloc_strategy = "BEST_FIT"
        if model == "SPOT":
            # With this strategy, "instance types that are less likely
            # to be interrupted are preferred" according to the AWS docs
            alloc_strategy = "SPOT_CAPACITY_OPTIMIZED"

        # Including recent generations (compared to default of m4/c4/r4) will result
        # in lower compute costs (e.g., $0.038/vCPU/hour vs $0.050/vCPU/hour).
        # Including multiple families will grant CEs with access to a greater pool
        # of instances when provisioning spot instances.
        instance_types = list(NONGPU_EC2_INSTANCE_TYPES)
        # Leaving this out based on Sage-Bionetworks-Workflows/nextflow-infra#161
        # instance_types.extend(GPU_EC2_INSTANCE_TYPES)

        # This is modeled after a request made in the Tower web client
        data = {
            "labelIds": label_ids,
            "computeEnv": {
                "name": name,
                "platform": "aws-batch",
                "credentialsId": credentials_id,
                "config": {
                    "cliPath": "/home/ec2-user/miniconda/bin/aws",
                    "computeJobRole": self.stack["TowerForgeBatchWorkJobRoleArn"],
                    "configMode": "Batch Forge",
                    "credentials": None,
                    "environment": None,
                    "executionRole": self.stack["TowerForgeBatchExecutionRoleArn"],
                    "fusion2Enabled": False,
                    "headJobCpus": 8,
                    "headJobMemoryMb": 15000,
                    "headJobRole": self.stack["TowerForgeBatchHeadJobRoleArn"],
                    "logGroup": None,
                    "nvnmeStorageEnabled": False,
                    "postRunScript": None,
                    "preRunScript": "NXF_OPTS='-Xms7g -Xmx14g'",
                    "region": self.org.aws.region,
                    "resourceLabelIds": label_ids,
                    "waveEnabled": True,
                    "workDir": f"s3://{self.stack['TowerScratch']}/work",
                    "forge": {
                        "allocStrategy": alloc_strategy,
                        "allowBuckets": [],
                        "containerRegIds": None,
                        "disposeOnDeletion": True,
                        "dragenEnabled": None,
                        "ebsAutoScale": True,
                        "ebsBlockSize": 1000,
                        "ebsBootSize": 1000,
                        "ec2KeyPair": None,
                        "ecsConfig": ECS_CONFIG.strip(),
                        "efsCreate": False,
                        "gpuEnabled": False,
                        "imageId": None,
                        "instanceTypes": instance_types,
                        "maxCpus": 1000,
                        "minCpus": 0,
                        "securityGroups": [],
                        "subnets": [self.org.vpc[o] for o in VPC_STACK_OUTPUT_SIDS],
                        "type": model,
                        "vpcId": self.org.vpc[VPC_STACK_OUTPUT_VID],
                    },
                },
            },
        }
        return data

    def create_compute_environment(self) -> Dict[str, Optional[str]]:
        """Create default compute environment under the given workspace

        Returns:
            Dict[str, Optional[str]]: Identifier for the compute environment
        """
        compute_env_ids: dict[str, Optional[str]] = {"SPOT": None, "EC2": None}
        # Create compute environment names}"
        comp_env_spot = f"{self.stack_name}-spot-{CE_VERSION}"
        comp_env_ec2 = f"{self.stack_name}-ondemand-{CE_VERSION}"
        # Check if compute environment has already been created for this project
        endpoint = "/compute-envs"
        params = {"workspaceId": self.id}
        response = self.tower.request("GET", endpoint, params=params)
        for comp_env in response["computeEnvs"]:
            if comp_env["platform"] == "aws-batch" and (
                comp_env["status"] == "AVAILABLE" or comp_env["status"] == "CREATING"
            ):
                if comp_env["name"] == comp_env_spot:
                    compute_env_ids["SPOT"] = comp_env["id"]
                elif comp_env["name"] == comp_env_ec2:
                    compute_env_ids["EC2"] = comp_env["id"]
        # Create any missing compute environments for the project
        if compute_env_ids["SPOT"] is None:
            data = self.generate_compute_environment(comp_env_spot, "SPOT")
            response = self.tower.request("POST", endpoint, params=params, json=data)
            compute_env_ids["SPOT"] = response["computeEnvId"]
            self.set_primary_compute_environment(response["computeEnvId"])
        if compute_env_ids["EC2"] is None:
            data = self.generate_compute_environment(comp_env_ec2, "EC2")
            response = self.tower.request("POST", endpoint, params=params, json=data)
            compute_env_ids["EC2"] = response["computeEnvId"]
        return compute_env_ids

    def set_primary_compute_environment(self, compute_env_id: str) -> None:
        """Mark the given compute environment as the primary one (default)

        Args:
            compute_env_id (str): Compute environment ID
        """
        endpoint = f"/compute-envs/{compute_env_id}/primary"
        params = {"workspaceId": self.id}
        self.tower.request("POST", endpoint, params=params, json="{}")


class TowerOrganization:
    def __init__(
        self,
        tower: TowerClient,
        projects: Projects,
        full_name: str = ORG_NAME,
        use_teams: bool = False,
    ) -> None:
        """Create Tower organization helper instance

        Args:
            tower (TowerClient): Nextflow Tower client
            projects (Projects): List of projects and their users
            full_name (str): (Optional) Full name of organization
        """
        self.aws = AwsClient()
        self.vpc = self.aws.get_cfn_stack_outputs(VPC_STACK_NAME)
        self.tower = tower
        self.full_name = full_name
        self.use_teams = use_teams
        self.name = self.tower.get_valid_name(full_name)
        self.json = self.create()
        self.id = self.json["orgId"]
        self.projects = projects
        self.users_per_project = projects.users_per_project
        self.tags_per_project = projects.tags_per_project
        self.teamids_per_project: Dict[str, Dict[int, str]] = dict()
        self.members: Dict[str, dict] = dict()
        self.populate()
        self.workspaces: Dict[str, TowerWorkspace] = dict()
        self.create_workspaces()

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
        endpoint = f"/orgs/{self.id}/members"
        params = {"search": user}
        response = self.tower.paged_request("GET", f"{endpoint}", params=params)
        matches = list(response)
        print(matches)
        if len(matches) == 1 and matches[0]["email"] == user:
            member = matches[0]
        else:
            data = {"user": user}
            print(data)
            response = self.tower.request("PUT", f"{endpoint}/add", json=data)
            print(response)
            member = response["member"]

        self.members[user] = member
        return member

    def add_member_to_team(self, team_id: int, user: str) -> int:
        """Add user to given team within an organization

        Args:
            team_id (int): Team identifier
            user (str): Email address for the user

        Returns:
            int: Team member identifier, which is the same as the
                organization member identifier
        """
        endpoint = f"/orgs/{self.id}/teams/{team_id}/members"
        data = {"userNameOrEmail": user}
        response = self.tower.request("POST", endpoint, json=data)
        # If the user is already a member, you get the following message:
        #   "The member is already associated with the team"
        # If this happens, just retrieve the member ID from the organization
        if "message" in response and "already" in response["message"]:
            member = self.add_member(user)
            member_id = member["memberId"]
        else:
            member_id = response["member"]["memberId"]
        return member_id

    def remove_member_from_team(self, team_id: int, member_id: int) -> Dict:
        """Remove a member from an organization team

        Args:
            team_id (int): Team identifier
            member_id (int): Member identifier
        """
        endpoint = f"/orgs/{self.id}/teams/{team_id}/members/{member_id}/delete"
        response = self.tower.request("DELETE", endpoint)
        return response

    def create_team(self, team_name: str) -> int:
        """Create team under organization with the given name

        Args:
            team_name (str): Team name

        Returns:
            int: Team identifier
        """
        # Check if the team already exists
        endpoint = f"/orgs/{self.id}/teams"
        teams = self.tower.paged_request("GET", endpoint)
        for team in teams:
            if team["name"] == team_name:
                return team["teamId"]
        # If team doesn't exist, create one
        data = {"team": {"name": team_name, "description": None, "avatar": None}}
        response = self.tower.request("POST", endpoint, json=data)
        return response["team"]["teamId"]

    def list_team_members(self, team_id: int) -> List[int]:
        """Retrieve a list of team member IDs

        Args:
            team_id (int): Team identifier

        Returns:
            List[int]: List of team member IDs
        """
        endpoint = f"/orgs/{self.id}/teams/{team_id}/members"
        team_members = self.tower.paged_request("GET", endpoint)
        team_member_ids = [member["memberId"] for member in team_members]
        return team_member_ids

    def populate(self) -> None:
        """Add all emails from across all projects to the organization

        Returns:
            Dict[str, dict]: Same as self.project, but with member IDs
        """
        for project_name, project_users in self.users_per_project.items():
            # Create and populate teams for each user group/role
            self.teamids_per_project[project_name] = dict()
            for users, user_group, role in project_users.list_teams():
                if self.use_teams:
                    project_prefix = project_name[:-8]  # Trim '-project' suffix
                    team_name = f"{project_prefix}-{user_group}"
                    team_id = self.create_team(team_name)
                    self.teamids_per_project[project_name][team_id] = role
                # Add expected team members
                verified_ids = set()
                for user in users:
                    member = self.add_member(user)
                    member_id = member["memberId"]
                    verified_ids.add(member_id)
                    if self.use_teams:
                        self.add_member_to_team(team_id, user)
                # Remove unexpected team members
                if self.use_teams:
                    for team_member_id in self.list_team_members(team_id):
                        if team_member_id not in verified_ids:
                            self.remove_member_from_team(team_id, team_member_id)

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
            tags = self.tags_per_project[name]
            if self.use_teams:
                teams = self.teamids_per_project[name]
                ws = TowerWorkspace(self, name, teams=teams, tags=tags)
            else:
                ws = TowerWorkspace(self, name, users=users, tags=tags)
            self.workspaces[name] = ws
            # Adding a short delay between creating each workspace
            # to allow time for compute environments to be deleted
            # before creating new ones and running into the limit
            time.sleep(30)
        return self.workspaces


def parse_args() -> argparse.Namespace:
    """Parse and validate command-line arguments

    Returns:
        argparse.Namespace: Parsed command-line arguments
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("projects_dir")
    parser.add_argument("--dry_run", "-n", action="store_true")
    parser.add_argument("--debug", "-d", action="store_true")
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    main()
