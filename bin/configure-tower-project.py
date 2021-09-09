#!/usr/bin/env python3

import argparse
import json
import os

import boto3
import requests


REGION = "us-east-1"


class TowerConfigurator:
    def __init__(self, stack_name, rw_users, ro_users):
        self.stack_name = stack_name
        self.rw_users = rw_users
        self.ro_users = ro_users
        self.nextflow_tower_token = os.environ["NXF_TOWER_TOKEN"]
        self.region = REGION
        self.session = boto3.session.Session()  # Using default profile
        self.tower_endpoint = self.get_tower_endpoint()

    def configure(self):
        project_stack = self.retrieve_cfn_stack(self.stack_name)
        vpc_stack = self.retrieve_cfn_stack("nextflow-vpc")
        sage_org_id, workspace_id = self.create_tower_workspace()
        self.create_tower_compute_env(project_stack, vpc_stack, workspace_id)
        self.add_workspace_participants(sage_org_id, workspace_id)

    def retrieve_cfn_stack(self, stack_name):
        cfn = self.session.client("cloudformation")
        response = cfn.describe_stacks(StackName=stack_name)
        stack = response["Stacks"][0]
        stack["ParametersDict"] = {
            p["ParameterKey"]: p["ParameterValue"] for p in stack["Parameters"]
        }
        stack["OutputsDict"] = {
            p["OutputKey"]: p["OutputValue"] for p in stack["Outputs"]
        }
        return stack

    def get_tower_endpoint(self):
        r53_stack = self.retrieve_cfn_stack("nextflow-r53-alias-record")
        hostname = r53_stack["OutputsDict"]["ConnectDNSRecord"]
        endpoint = f"https://{hostname}/api"
        return endpoint

    def retrieve_secret(self, secret_arn):
        secretsmanager = self.session.client("secretsmanager")
        response = secretsmanager.get_secret_value(SecretId=secret_arn)
        secret_value = json.loads(response["SecretString"])
        return secret_value

    def make_tower_request(self, type, endpoint, params=None, data=None):
        token = self.nextflow_tower_token
        headers = {
            "Accept": "application/json, application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        request_fn = getattr(requests, type)
        full_url = self.tower_endpoint + endpoint
        if data is not None:
            response = request_fn(full_url, params=params, json=data, headers=headers)
        else:
            response = request_fn(full_url, params=params, headers=headers)
        return response

    def create_tower_organization(self):
        # Return Sage organization if it already exists
        response = self.make_tower_request("get", "/orgs")
        orgs = response.json()["organizations"]
        for org in orgs:
            if org["name"] == "Sage-Bionetworks":
                return org["orgId"]
        # Otherwise, create it
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
        response = self.make_tower_request("post", "/orgs", data=data)
        sage_org_id = response.json()["organization"]["orgId"]
        return sage_org_id

    def create_tower_workspace(self):
        # Return project workspace if it already exists
        sage_org_id = self.create_tower_organization()
        response = self.make_tower_request("get", f"/orgs/{sage_org_id}/workspaces")
        workspaces = response.json()["workspaces"]
        for workspace in workspaces:
            if workspace["name"] == self.stack_name:
                return sage_org_id, workspace["id"]
        # Otherwise, create it
        data = {
            "workspace": {
                "name": self.stack_name,
                "fullName": self.stack_name,
                "description": None,
                "visibility": "PRIVATE",
            }
        }
        response = self.make_tower_request(
            "post", f"/orgs/{sage_org_id}/workspaces", data=data
        )
        workspace_id = response.json()["workspace"]["id"]
        return sage_org_id, workspace_id

    def create_tower_credentials(self, project_stack, workspace_id=None):
        # Check if credentials already exist for this stack
        url_params = {"workspaceId": workspace_id}
        response = self.make_tower_request("get", "/credentials", url_params)
        creds = response.json()["credentials"]
        for cred in creds:
            if cred["name"] == self.stack_name:
                assert cred["provider"] == "aws"
                assert cred["deleted"] is None
                return cred["id"]
        # If not, create them
        secret_arn = project_stack["OutputsDict"][
            "TowerForgeServiceUserAccessKeySecretArn"
        ]
        credentials = self.retrieve_secret(secret_arn)
        role_arn = project_stack["OutputsDict"]["TowerForgeServiceRoleArn"]
        data = {
            "credentials": {
                "name": self.stack_name,
                "provider": "aws",
                "keys": {
                    "accessKey": credentials["aws_access_key_id"],
                    "secretKey": credentials["aws_secret_access_key"],
                    "assumeRoleArn": role_arn,
                },
                "description": f"Credentials for {self.stack_name}",
            }
        }
        response = self.make_tower_request("post", "/credentials", url_params, data)
        response_data = response.json()
        creds_id = response_data["credentialsId"]
        return creds_id

    def create_tower_compute_env(self, project_stack, vpc_stack, workspace_id=None):
        # Check if compute environment already exist for this stack
        url_params = {"workspaceId": workspace_id}
        response = self.make_tower_request("get", "/compute-envs", url_params)
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
        bucket_name = project_stack["OutputsDict"]["TowerBucket"]
        forge_head_role_arn = project_stack["OutputsDict"][
            "TowerForgeBatchHeadJobRoleArn"
        ]
        forge_work_role_arn = project_stack["OutputsDict"][
            "TowerForgeBatchWorkJobRoleArn"
        ]
        vpc_id = vpc_stack["OutputsDict"]["VPCId"]
        subnet_ids = [
            vpc_stack["OutputsDict"]["PrivateSubnet"],
            vpc_stack["OutputsDict"]["PrivateSubnet1"],
            vpc_stack["OutputsDict"]["PrivateSubnet2"],
            vpc_stack["OutputsDict"]["PrivateSubnet3"],
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
        response = self.make_tower_request("post", "/compute-envs", url_params, data)
        response_data = response.json()
        comp_env_id = response_data["computeEnvId"]
        return comp_env_id

    def add_organization_member(self, org_id, user):
        # Attempt to create new user
        org_add_data = {"user": user}
        response = self.make_tower_request(
            "put",
            f"/orgs/{org_id}/members/add",
            data=org_add_data,
        )
        if "message" in response.json():
            message = response.json()["message"]
            assert "already a member" in message
            user_name = message.split("'")[1]
            response = self.make_tower_request("get", f"/orgs/{org_id}/members")
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
        response = self.make_tower_request(
            "put",
            f"/orgs/{org_id}/workspaces/{workspace_id}/participants/add",
            data=data,
        )
        if "message" in response.json():
            message = response.json()["message"]
            assert message == "Already a participant"
            response = self.make_tower_request(
                "get", f"/orgs/{org_id}/workspaces/{workspace_id}/participants"
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
        self.make_tower_request(
            "put",
            f"/orgs/{org_id}/workspaces/{workspace_id}/participants/{part_id}/role",
            data=data,
        )

    def add_workspace_participants(self, org_id, workspace_id):
        for user in self.rw_users + self.ro_users:
            member_id = self.add_organization_member(org_id, user)
            part_id = self.add_workspace_participant(org_id, workspace_id, member_id)
            role = "maintain" if user in self.rw_users else "view"
            self.update_workspace_role(org_id, workspace_id, part_id, role)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stack_name", "-s", required=True)
    parser.add_argument("--rw_users", "-w", nargs="*", help="Read/write users")
    parser.add_argument("--ro_users", "-r", nargs="*", help="Read-only users")
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = parse_args()
    tower = TowerConfigurator(args.stack_name, args.rw_users, args.ro_users)
    tower.configure()
