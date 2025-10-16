# Contribution Guidelines

For more information on how this repository was set up, check out this Confluence [**how-to page**](https://sagebionetworks.jira.com/wiki/spaces/IT/pages/2058878986) on how to bootstrap AWS accounts (access limited to Sage Bionetworks staff).

## Getting Started

There are important details on how the infrastructure is set up and how this repository is organized under the following sections, such as [AWS Accounts](#aws-accounts) and [Repository Organization](#repository-organization).

### Setting up the repository for development

You must first install [`pipenv`](https://pipenv.pypa.io/en/latest/install/#installing-pipenv) and the [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html).

For testing, you can use the Administrator IAM role on the `nextflow-dev` AWS account. If you don't have access to this role, ask a Tower admin to request that you be granted permission. While using the `nextflow-dev` admin role, you should only deploy the stacks within the `common` and `*-dev` folders (see [Configuration](#configuration)). The instructions below assume that you have already configured your IAM role with the AWS CLI.

```console
# Create directory for remote sceptre templates
mkdir -p templates/remote/

# Install dependencies in an isolated virtual environment
pipenv install --dev

# Install pre-commit hooks into Git
pipenv run pre-commit install
```

### Testing sceptre deployment

If your text editor (_e.g._ Visual Studio Code) or shell (_e.g._ using [`direnv`](https://direnv.net/)) can automatically activate the `pipenv` virtual environment, you can omit the `pipenv shell` command.

```console
# Define the AWS CLI profile you want to use for testing
export AWS_PROFILE="<profile-name>"

# Test the deployment of a specific 'develop' stack
pipenv run sceptre --var-file ./src/sceptre/variables/dev.yaml launch --yes infra-dev/some-stack.yaml

# Delete the test deployment of the specific 'develop' stack
pipenv run sceptre --var-file ./src/sceptre/variables/dev.yaml delete --yes infra-dev/some-stack.yaml
```

## AWS Accounts

Two AWS accounts are managed by this repository, both of which were [bootstrapped](https://sagebionetworks.jira.com/wiki/spaces/IT/pages/2058878986/Bootstrapping+AWS+Project+Accounts) using [org-formation](https://github.com/org-formation/org-formation-cli). They are defined in this [organization.yaml](https://github.com/Sage-Bionetworks-IT/organizations-infra/blob/master/org-formation/organization.yaml) file. The two accounts are:

- `workflows-nextflow-prod` (or `nextflow-prod`) for production use
- `workflows-nextflow-dev` (or `nextflow-dev`) for testing purposes
- `org-sagebase-strides-ampad-workflows` (or `strides-ampad`) for production use within the AMP-AD project (AWS bills directly to the NIH) and should be treated like `nextflow-prod`

In general, we use the `nextflow-dev` account for testing templates before deploying them into the `nextflow-prod` account. New [template configurations](#configuration) don't necessarily need to go through `nextflow-dev` first. For example, new instances of the `tower-project.j2` template don't need to be deployed in `nextflow-dev` first.

### Role-Based Access

Human access to these AWS accounts (programmatically or via the Management Console) is provided using IAM roles defined in [organizations-infra](https://github.com/Sage-Bionetworks-IT/organizations-infra/blob/master/org-formation/700-aws-sso/_tasks.yaml) (search for "WorkflowsNextflow"). These roles are individually [bound](https://github.com/Sage-Bionetworks-IT/organizations-infra/blob/master/org-formation/700-aws-sso/README.md) to user groups in JumpCloud, which are managed by Sage IT.

- **TowerViewer:** This role is available in both `nextflow-dev` and `nextflow-prod` and grants access to the relevant subset of permissions in [`ViewOnlyAccess`](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_job-functions.html#jf_view-only-user).
- **Developer-IAM-Contrained:** This role is only available in `nextflow-dev` for testing and development purposes and is attached to the [`PowerUserAccess`](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_job-functions.html#jf_developer-power-user) managed policy and some IAM access, _i.e._ you can only create/edit/delete IAM resources that have the `dev-` prefix in their names, so that important IAM resources aren't disrupted.
- **Administrator:** This role exists in both the `nextflow-dev` and `nextflow-prod` accounts (with separate user groups in JumpCloud) and grants full access, _i.e._ [`AdministratorAccess`](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_job-functions.html#jf_administrator).

## Repository Organization

This repository follows the standard [Sceptre directory structure](https://sceptre.cloudreach.com/2.6.3/docs/get_started.html#directory-structure).

### Templates

Bespoke [CloudFormation templates](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/template-guide.html) are stored in the `templates/` directory, whereas general-purpose templates are obtained from the [aws-infra](https://github.com/Sage-Bionetworks/aws-infra/tree/master/templates) repository during deployment. These external templates are downloaded into the `templates/remote/` subdirectory using pre-launch [Sceptre hooks](https://sceptre.cloudreach.com/2.6.3/docs/hooks.html) ([example](https://github.com/Sage-Bionetworks-Workflows/aws-workflows-nextflow-infra/blob/db37741e53fa5276b33b24d1af247d8d29bc0e56/config/prod/nextflow-vpc.yaml#L6-L8)).

### Configuration

Instances of each template are configured to be deployed in the `config/` directory, which is organized into subfolders known as stack groups. In this case, we have defined several stack groups: `common`, `infra-*`, and `projects-*`. The [CI/CD](#cicd) workflow deploys these stack groups to the [AWS accounts](#aws-accounts) as follows (in the listed order):

- `common` and `*-dev` to the `nextflow-dev` account
- `common` and `*-prod` to the `nextflow-prod` account
- `common` and `*-ampad` to the `strides-ampad` account

There are two types of [stack group configurations](https://sceptre.cloudreach.com/2.6.3/docs/stack_group_config.html) used in this repository. First, we have a shared [`config/config.yaml`](config/config.yaml) configuration, which contains values that are applicable to all stack groups. Second, we have configurations that are specific to individual stack groups, which define account-specific values (like IAM role ARNs).

### CI/CD

[GitHub Actions](https://github.com/features/actions) are used for continuous integration and deployment (CI/CD). Currently, this repository is configured with a single workflow, [rw-deploy](.github/workflows/rw-deploy.yaml), which runs some lint checks and conditionally deploys the [stacks](#configuration) on pushes to the `main` branch.

The lint checks are defined as [pre-commit hooks](.pre-commit-config.yaml) and are partially configured by the [.yamllint](.yamllint) file. See [above](#setting-up-the-repository-for-development) for how to locally set up pre-commit hooks in Git to ensure that these checks are run before every commit.

The CI/CD workflow uses a matrix strategy in conjunction with repository environments. See [below](#secrets) for more information on secrets managements.

**N.B.** If the CI/CD workflow fails (either due to new commits or earlier commits), some changes might not get deployed. You can check the state of deployments from the `main` branch [here](https://github.com/Sage-Bionetworks-Workflows/aws-workflows-nextflow-infra/actions?query=event%3Apush+branch%3Amain).

### Dependencies

This repository uses the [Pipenv](https://pipenv.pypa.io/) Python package to manage dependencies. The main dependencies and their required versions (if applicable) are listed in the [Pipfile](Pipfile) whereas the [Pipfile.lock](Pipfile.lock) lists all recursive dependencies, their versions, and their checksums at the time of generating the lockfile. This Pipenv environment is used for [CI/CD](#cicd), but it can also be used for local development and testing. See [above](#setting-up-the-repository-for-development) for how to set up a local development environment using Pipenv.

Additional dependencies exist for the [pre-commit hooks](.pre-commit-config.yaml) that we've added to this repository. The virtual environments for these hooks are automatically configured when you run `pre-commit`.

### Scripts

- `bin/mirror-igenomes.sh`: This Bash script is manually run to synchronize a subset of human and mouse reference files from the [nf-core iGenomes bucket](https://ewels.github.io/AWS-iGenomes/) to a Sage-owned bucket in `us-east-1`. There are multiple reasons: (1) Sage AWS accounts cannot make requests to regions outside of the US; (2) we don't want nf-core to incur egress charges on our behalf; (3) creating a local mirror in `us-east-1` should reduce latency; and (4) we own a copy of the reference files in case anything happens to the nf-core bucket (_e.g._ AWS funding being cut). At the moment, this script is intended to be run manually because reference files shouldn't change all that often and thus automating the process wasn't deemed worth the effort.

## Secrets

The [CI/CD workflow](#cicd) and [Sceptre configurations](#configuration) make use of the following secrets.

### GitHub Organization Secrets

After switching to a matrix strategy in the CI/CD workflow, all secrets are being stored in repository environments (see [below](#github-repository-secrets)). Organization secrets are no longer being used.

### GitHub Repository Secrets

Our GitHub secrets are stored in [account-specific environments](https://github.com/Sage-Bionetworks-Workflows/nextflow-infra/settings/environments). These secrets contain AWS and Nextflow Tower credentials.

The Github OIDC for GH actions were bootstrapped in the [`organizations-infra`](https://github.com/Sage-Bionetworks-IT/organizations-infra/) repository. For `nextflow-dev` and `nextflow-prod`, look for `GithubOidcWorkflowsDevNextflowInfra` in [this file](https://github.com/Sage-Bionetworks-IT/organizations-infra/blob/master/org-formation/650-identity-providers/_tasks.yaml). For `strides-ampad`, look at [this file](https://github.com/Sage-Bionetworks-IT/organizations-infra/blob/master/sceptre/strides-ampad-workflows/config/prod/github-oidc-nextflow-infra.yaml).

The Nextflow Tower credentials (_i.e._ access tokens) were created manually using the Google service accounts that we provisioned for creating the Google OAuth clients, `nextflowgdev.dev@sagebase.org` and `nextflowgdev.prod@sagebase.org`, respectively. The login info for these two Google accounts are stored in LastPass under the `Shared-IBC-DPE-Workflows` folder. Note that the `*-prod` and `*-ampad` stacks are configured to use the token associated with `nextflowgdev.prod@sagebase.org` whereas the `*-dev` stacks are configured to use the token associated with `nextflowgdev.dev@sagebase.org`.

- `TOWER_TOKEN`: The Nextflow Tower access token that will be used to provision the Tower teams, workspaces, credentials, and compute environments.

### AWS Secrets

The following secrets were manually created in AWS Secrets Manager. They are used in some [Sceptre configurations](#configuration) and are retrieved using a [Sceptre resolver](https://github.com/iAnomaly/sceptre-resolver-aws-secrets-manager). We also create secrets during deployment and store them in Secrets Manager ([example](https://github.com/Sage-Bionetworks-Workflows/aws-workflows-nextflow-infra/blob/db37741e53fa5276b33b24d1af247d8d29bc0e56/templates/nextflow-tower-secret.yaml#L14-L34)), but these aren't listed here. These are encrypted using the `workflows-infra` KMS key.

- `nextflow/license`: The paid license key for Nextflow Tower
- `nextflow/google_oauth_app`: The Google OAuth client credentials
- `nextflow/github_service_acct`: The GitHub service account credentials
- `nextflow/synapse_oauth_client`: The Synapse OAuth client ID and secret

The following secrets were created in all AWS accounts (including `strides-ampad`). Note that personal access tokens were used as password where possible (see notes in LastPass). Each of these secrets were created with two key-value pairs (`username` and `password`). Another service account (`nextflow/ecr_service_acct`) is created using CloudFormation (see `wave-ecr-user` stack).

- `nextflow/dockerhub_service_acct`: The Docker Hub service account credentials for the Wave service
- `nextflow/ghcr_service_acct`: The GHCR service account credentials for the Wave service
- `nextflow/quayio_service_acct`: The Quay.io service account credentials for the Wave service

## Deployment Testing

After a new deployment has successfully completed, it is important to ensure things are working as expected by doing the following:

1. Launch a simple workflow such as `nextflow-io/hello` from the UI using both `spot` and `on-demand` compute environments.
1. Run the `demo.py` [script](https://github.com/Sage-Bionetworks-Workflows/py-orca/blob/main/demo.py) from the `py-orca` repository. Make sure that your connection URI environment variable points to the correct URL and workspace. This will check that the API is working as expected and that individual workspaces are able to access their associated S3 buckets.

## Additional Notes

- The CIDR ranges of IP addresses specifies in the VPC configurations were added to the [Sage VPN](https://sagebionetworks.jira.com/wiki/spaces/IT/pages/352976898/Sage+VPN) table.
