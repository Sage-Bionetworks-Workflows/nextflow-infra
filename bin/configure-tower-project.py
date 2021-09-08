#!/usr/bin/env python3

import argparse
import json
import os

import boto3
import requests


REGION = "us-east-1"


class TowerConfigurator:
    def __init__(self, stack_name):
        self.stack_name = stack_name
        self.nextflow_tower_token = os.environ["NXF_TOWER_TOKEN"]
        self.region = REGION
        self.session = boto3.session.Session()  # Using default profile
        self.tower_endpoint = self.get_tower_endpoint()

    def configure(self):
        project_stack = self.retrieve_cfn_stack(self.stack_name)
        vpc_stack = self.retrieve_cfn_stack("nextflow-vpc")
        self.create_tower_compute_env(project_stack, vpc_stack)

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

    def make_tower_request(self, type, endpoint, data=None):
        token = self.nextflow_tower_token
        headers = {
            "Accept": "application/json, application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        request_fn = getattr(requests, type)
        full_url = self.tower_endpoint + endpoint
        if type == "post":
            response = request_fn(full_url, json=data, headers=headers)
        else:
            response = request_fn(full_url, headers=headers)
        return response

    def create_tower_credentials(self, project_stack):
        # Check if credentials already exist for this stack
        response = self.make_tower_request("get", "/credentials")
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
        response = self.make_tower_request("post", "/credentials", data)
        response_data = response.json()
        creds_id = response_data["credentialsId"]
        return creds_id

    def create_tower_compute_env(self, project_stack, vpc_stack):
        # Check if compute environment already exist for this stack
        response = self.make_tower_request("get", "/compute-envs")
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
        creds_id = self.create_tower_credentials(project_stack)
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
        response = self.make_tower_request("post", "/compute-envs", data)
        response_data = response.json()
        comp_env_id = response_data["computeEnvId"]
        return comp_env_id


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stack_name", "-s")
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = parse_args()
    tower = TowerConfigurator(args.stack_name)
    tower.configure()
