# Contribution Guidelines

For more information on how this repository was set up, check out this Confluence [**how-to page**](https://sagebionetworks.jira.com/wiki/spaces/IT/pages/2058878986) on how to bootstrap AWS accounts.

## Setting up the repository for development

You must first install [`pipenv`](https://pipenv.pypa.io/en/latest/install/#installing-pipenv) and the [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html).

For testing, you can use the `workflows-nextflow-dev` AWS account that was set up [here](https://github.com/Sage-Bionetworks-IT/organizations-infra/blob/3dfe3fe2db327bd07cf31610cd77f02c3bacc130/org-formation/organization.yaml#L316-L326). You can [open an issue](https://github.com/Sage-Bionetworks-Workflows/aws-workflows-nextflow-infra/issues/new/choose) to request for access to the AWS account. One of the project admins will create an IAM user in this AWS account and share the credentials in a secure way.

```
# Create directory for remote sceptre templates
mkdir -p templates/remote/

# Install dependencies in isolated virtual environment
pipenv install --dev

# Install pre-commit hooks into Git
pipenv run pre-commit install

# Set up an AWS CLI profile with admin access for a test account
aws configure --profile $AWS_PROFILE
```

## Testing sceptre deployment

If your text editor (_e.g._ Visual Studio Code) or shell (_e.g._ using [`direnv`](https://direnv.net/)) can automatically activate the `pipenv` virtual environment, you can omit the `pipenv shell` command.

```
# Activate the pipenv virtual environment to use sceptre
pipenv shell

# Test the deployment of the 'prod' stack group
sceptre --var "profile=$AWS_PROFILE" launch --yes prod

# Delete the test deployment of the 'prod' stack group
sceptre --var "profile=$AWS_PROFILE" delete --yes prod
```
