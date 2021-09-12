#!/usr/bin/env python3

from copy import deepcopy
import os

import boto3
from botocore.stub import Stubber
import pytest

import configure_tower

CONFIG_DIR = "config/"


class TestUsers:
    valid_args = {
        "maintainers": ["bruno.grande@sagebase.org", "tess.thyer@sagebase.org"],
        "viewers": ["thomas.yu@sagebase.org"],
    }

    def test__init__(self):
        users = configure_tower.Users(**self.valid_args)
        assert users.owners == []
        assert users.admins == []
        assert users.maintainers == self.valid_args["maintainers"]
        assert users.launchers == []
        assert users.viewers == self.valid_args["viewers"]

    def test_list_users(self):
        users = configure_tower.Users(**self.valid_args)
        user_list = list(users.list_users())
        assert len(user_list) == sum(map(len, self.valid_args.values()))


class TestProjects:
    # Generate lists of valid and invalid strings
    valid_project_names = ["foo-project", "bar-project"]
    valid_project_filenames = [f"{x}.yaml" for x in valid_project_names]
    valid_project_filepaths = [os.path.join(CONFIG_DIR, x) for x in valid_project_names]
    valid_emails = [
        "bruno.grande@sagebase.org",
        "tess.thyer@sagebase.org",
        "thomas.yu@sagebase.org",
    ]
    valid_arn_prefixes = [
        "arn:aws:sts::563295687221:assumed-role/AWSReservedSSO_Viewer_19d3ce703c9acf2e",
        "arn:aws:sts::563295687221:assumed-role/AWSReservedSSO_Developer_baa6fed639faf5e7",
        "arn:aws:sts::563295687221:assumed-role/AWSReservedSSO_Administrator_934edbf73c05264e",
    ]
    valid_arns = list(map("/".join, zip(valid_arn_prefixes, valid_emails)))
    invalid_arns = [
        "arn:aws:iam::035458030717:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_Administrator_580e9f32ac55c4e7",
        "arn:aws:sts::035458030717:assumed-role/AWSReservedSSO_Viewer_fd80909e6a51c6e7/thomas.yu",
        "arn:aws:sts::035458030717:assumed-role/AWSReservedSSO_Viewer_fd80909e6a51c6e7",
    ]

    # Generate valid projects
    valid_project_1 = {
        "template_path": "tower-project.yaml",
        "stack_name": valid_project_names[0],
        "parameters": {
            "S3ReadWriteAccessArns": valid_arns[0:1],
        },
    }
    valid_project_2 = {
        "template_path": "tower-project.yaml",
        "stack_name": valid_project_names[1],
        "parameters": {
            "S3ReadWriteAccessArns": "",
            "S3ReadOnlyAccessArns": valid_arns[1:3],
        },
    }
    valid_projects = [valid_project_1, valid_project_2]

    # Generate invalid projects from the valid ones
    invalid_project_1 = deepcopy(valid_project_1)
    invalid_project_1["parameters"] = {}
    invalid_project_2 = deepcopy(valid_project_2)
    del invalid_project_2["stack_name"]
    invalid_projects = [invalid_project_1, invalid_project_2]

    @pytest.fixture
    def projects(self, mocker):
        mocker.patch.object(configure_tower.Projects, "extract_users")
        return configure_tower.Projects(CONFIG_DIR)

    def test__init__(self, mocker):
        mocker.patch.object(configure_tower.Projects, "extract_users")
        projects = configure_tower.Projects(CONFIG_DIR)
        projects.extract_users.assert_called_once()

    def test_list_projects(self, projects, mocker):
        valid_names = self.valid_project_filenames
        invalid_names = ["ignore.yaml" + "baz-project.txt"]
        return_value = [(CONFIG_DIR, [], valid_names + invalid_names)]
        mocker.patch("os.walk", return_value=return_value)
        expected = [os.path.join(CONFIG_DIR, x) for x in valid_names]
        actual = list(projects.list_projects())
        assert actual == expected
        os.walk.assert_called_once()

    def test_load_projects_valid(self, projects, mocker):
        return_value = iter(self.valid_project_filenames)
        mocker.patch.object(projects, "list_projects", return_value=return_value)
        mocker.patch("builtins.open")
        mocker.patch("yaml.load", side_effect=iter(self.valid_projects))
        expected = self.valid_projects
        actual = list(projects.load_projects())
        assert actual == expected
        projects.list_projects.assert_called_once()
        open.assert_called_with(self.valid_project_filenames[-1])

    def test_load_projects_invalid(self, projects, mocker):
        return_value = iter(self.valid_project_filenames)
        mocker.patch.object(projects, "list_projects", return_value=return_value)
        mocker.patch("builtins.open")
        invalid_projects = [{"foo": "bar"}, {"template_path": "baz"}]
        mocker.patch("yaml.load", side_effect=iter(invalid_projects))
        expected = list()
        actual = list(projects.load_projects())
        assert actual == expected
        projects.list_projects.assert_called_once()
        open.assert_called_with(self.valid_project_filenames[-1])

    def test_extract_emails_valid(self, projects):
        input = self.valid_arns
        expected = self.valid_emails
        actual = projects.extract_emails(input)
        assert actual == expected

    def test_extract_emails_empty(self, projects):
        input = ""
        expected = []
        actual = projects.extract_emails(input)
        assert actual == expected

    def test_extract_emails_invalid(self, projects):
        for arn in self.invalid_arns:
            with pytest.raises(ValueError):
                projects.extract_emails([arn])

    def test_extract_users_valid(self, mocker):
        mocker.patch.object(
            configure_tower.Projects,
            "load_projects",
            return_value=iter(self.valid_projects),
        )
        mocker.patch.object(
            configure_tower.Projects,
            "extract_emails",
            side_effect=lambda x: ["foo"] if len(x) > 0 else [],
        )
        mocker.patch.object(configure_tower, "Users")
        actual = configure_tower.Projects(CONFIG_DIR)
        assert list(actual.users_per_project.keys()) == self.valid_project_names
        actual.load_projects.assert_called_once()
        configure_tower.Users.assert_has_calls(
            [
                mocker.call(maintainers=["foo"], viewers=[]),
                mocker.call(maintainers=[], viewers=["foo"]),
            ]
        )

    def test_extract_users_invalid(self, mocker):
        for invalid_project in self.invalid_projects:
            mocker.patch.object(
                configure_tower.Projects,
                "load_projects",
                return_value=iter([invalid_project]),
            )
            with pytest.raises(AssertionError):
                configure_tower.Projects(CONFIG_DIR)


class TestAwsClient:
    @pytest.fixture
    def aws_client(self):
        return configure_tower.AwsClient()

    def test__init__(self, aws_client):
        assert aws_client.region == configure_tower.REGION
        assert isinstance(aws_client.session, boto3.session.Session)
        assert aws_client.session.region_name == configure_tower.REGION

    def test_get_cfn_stack_outputs(self, aws_client, mocker):
        stack_name = "foo"
        cfn = aws_client.session.client("cloudformation")
        response = {
            "Stacks": [
                {
                    "StackName": stack_name,
                    "Outputs": [
                        {
                            "OutputKey": "k1",
                            "OutputValue": "v1",
                        },
                        {
                            "OutputKey": "k2",
                            "OutputValue": "v2",
                        },
                    ],
                    "CreationTime": "2000-01-01",
                    "StackStatus": "CREATE_COMPLETE",
                }
            ],
        }
        expected_params = {"StackName": stack_name}
        expected_output = {"stack_name": stack_name, "k1": "v1", "k2": "v2"}
        with Stubber(cfn) as stubber:
            stubber.add_response("describe_stacks", response, expected_params)
            mocker.patch.object(aws_client.session, "client", return_value=cfn)
            stack = aws_client.get_cfn_stack_outputs(stack_name)
            assert stack == expected_output

    def test_get_secret_value(self, aws_client, mocker):
        secret_arn = "arn:aws:secretsmanager:us-east-1:012345:secret:abc123"
        sm = aws_client.session.client("secretsmanager")
        response = {"SecretString": '{"k1": "v1", "k2": "v2"}'}
        expected_params = {"SecretId": secret_arn}
        expected_output = {"k1": "v1", "k2": "v2"}
        with Stubber(sm) as stubber:
            stubber.add_response("get_secret_value", response, expected_params)
            mocker.patch.object(aws_client.session, "client", return_value=sm)
            stack = aws_client.get_secret_value(secret_arn)
            assert stack == expected_output


class TestTowerClient:
    pass


class TestTowerWorkspace:
    pass


class TestTowerOrganization:
    pass
