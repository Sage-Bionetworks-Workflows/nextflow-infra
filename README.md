# Nextflow Workflows Infrastructure

The AWS infrastructure for hosting a private instance of [Nextflow Tower](https://tower.nf/) and executing [Nextflow workflows](https://nextflow.io/) is defined in this repository and deployed using [CloudFormation](https://aws.amazon.com/cloudformation/) via [Sceptre](https://sceptre.cloudreach.com/).

## Onboarding

To complete these onboarding instructions, you will need a project name (_e.g._ `imcore`, `amp-ad`, `commonmind`). The stack name consists of the project name with the `-project` suffix (_e.g._ `imcore-project`, `amp-ad-project`, `commonmind-project`). Please update any instances of `<stack_name>` with the stack name (without the angle brackets).

1. Install [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) and [Docker Desktop](https://www.docker.com/products/docker-desktop).
2. Open a pull request on this repository in which you duplicate `config/prod/example-project.yaml` as `config/prod/<stack_name>.yaml` and update the contents as follows:
   1. Set the `stack_name` field to `<stack_name>`.
   2. Update the email at the end of the line under `ReadWriteAccessArns` to your own (using `@sagebase.org`).
   3. Duplicate the line under `ReadWriteAccessArns` for anyone else who should have write-access to this project, updating the email suffix accordingly.
   4. If anyone should only have read-access, uncomment the two lines for `ReadOnlyAccessArns` and update the email accordingly, duplicating as needed.
   5. Update the values for `Department` and `Project` under `stack_tags` such that billing can be properly routed as well as `OwnerEmail` so we know who to contact if the need arises.
3. Once the pull request is merged, open a terminal and perform the following steps:
   1. [Copy](https://d-906769aa66.awsapps.com/start#/) the temporary credentials for your Developer `sandbox` role, available under:
      ```
      AWS Accounts > org-sagebase-sandbox > Developer > Command line or programmatic access > Option 1
      ```
      Run the copied `export` commands, which should look like this:
      ```
      export AWS_ACCESS_KEY_ID="..."
      export AWS_SECRET_ACCESS_KEY="..."
      export AWS_SESSION_TOKEN="..."
      ```
      <!-- TODO: Insert GIF screencast -->
   2. [Create](https://tower.nf/tokens) a new token in Nextflow Tower called `<stack_name>`, copy the token (which is only ever displayed once), and run the following command, updating `<token>` with the copied value:
      <!-- TODO: Update link with our production instance of Tower -->
      ```
      export NXF_TOWER_TOKEN="<token>"
      ```
      <!-- TODO: Insert GIF screencast -->
   3. [Create](https://www.synapse.org/#!PersonalAccessTokens:) a new personal access token in Synapse called `<stack_name>`, copy the token (which is only ever displayed once), and run the following command, updating `<token>` with the copied value:
      ```
      export SYNAPSE_TOKEN="<token>"
      ```
      <!-- TODO: Insert GIF screencast -->
   4. Run the following Docker command; don't forget to update `<stack_name>` accordingly:
      ```
      STACK_NAME="<stack_name>"
      mkdir -p "~/.tower-projects/"
      docker run -e STACK_NAME -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN -e NXF_TOWER_TOKEN -e SYNAPSE_TOKEN -v "$HOME/.aws:/root/.aws" sagebionetworks/setup-tower-project > "~/.tower-projects/$STACK_NAME.json"
      ```
4. The above Docker command performs the following tasks:
   - Two AWS CLI profiles were added to `~/.aws/config`:
     - `tower-user`: Read-only access to everything that's non-sensitive in the production AWS account for Nextflow Tower.
     - `<stack_name>`: Write-access to the project-specific S3 bucket depending on whether you were listed under `ReadWriteAccessArns` or `ReadOnlyAccessArns`
   - In Nextflow Tower, the credentials for the service user with access to AWS Batch and your project bucket were automatically configured under the name `<stack_name>`.
   - In Nextflow Tower, a compute environment was pre-configured under the name `<stack_name> (default)` using the above credentials, the project bucket, the appropriate VPC, and otherwise default options. If you need to tweak the compute environment, we recommend that you clone the default one and make adjustments as necessary.

## AWS Accounts

Two AWS accounts are managed by this repository, both of which were [bootstrapped](https://sagebionetworks.jira.com/wiki/spaces/IT/pages/2058878986/Bootstrapping+AWS+Project+Accounts) using [org-formation](https://github.com/org-formation/org-formation-cli). They are defined in this [organization.yaml](https://github.com/Sage-Bionetworks-IT/organizations-infra/blob/master/org-formation/organization.yaml) file. The two accounts are:

- `workflows-nextflow-prod` (or `nextflow-prod`) for production use
- `workflows-nextflow-dev` (or `nextflow-dev`) for testing purposes

In general, we use the `nextflow-dev` account for testing templates before deploying them into the `nextflow-prod` account. New [template configurations](#configuration) don't necessarily need to go through `nextflow-dev` first.

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

Instances of each template are configured to be deployed in the `config/` directory, which is organized into subfolders known as stack groups. In this case, we have defined three stack groups: `common`, `develop`, and `prod`. The [CI/CD](#cicd) workflow deploys these stack groups to the [AWS accounts](#aws-accounts) as follows (in the listed order):

- `common` and `develop` to the `workflows-nextflow-dev` account
- `common` and `prod` to the `workflows-nextflow-prod` account

All three stack groups currently share the same [stack group configuration](https://sceptre.cloudreach.com/2.6.3/docs/stack_group_config.html): [`config/config.yaml`](config/config.yaml). Two values in this configuration file can be tweaked when running Sceptre, namely `profile` and `region`. The default region (`us-east-1`) is typically left as is, but the profile variable is useful for local testing. Our [contribution guidelines](CONTRIBUTING.md) describe how to use the Sceptre `--var` CLI option to specify an AWS CLI profile to use for deployment.

### CI/CD

[GitHub Actions](https://github.com/features/actions) are used for continuous integration and deployment. Currently, this repository is configured with a single workflow, [aws-deploy](.github/workflows/aws-deploy.yaml), which runs some lint checks and conditionally deploys the [stacks](#configuration) on pushes to the `main` branch.

The lint checks are defined as [pre-commit hooks](.pre-commit-config.yaml) and are partially configured by the [.yamllint](.yamllint) file. Our [contribution guidelines](CONTRIBUTING.md) describe how to locally set up pre-commit hooks in Git to ensure that these checks are run before every commit.

### Dependencies

This repository uses the [Pipenv](https://pipenv.pypa.io/) Python package to manage dependencies. The main dependencies and their required versions (if applicable) are listed in the [Pipfile](Pipfile) whereas the [Pipfile.lock](Pipfile.lock) lists all recursive dependencies, their versions, and their checksums at the time of generating the lockfile. This Pipenv environment is used for [CI/CD](#cicd), but it can also be used for local development and testing. Our [contribution guidelines](CONTRIBUTING.md) detail how to set up a local development environment using Pipenv.

## Secrets

The [CI/CD workflow](#cicd) uses secrets stored at the level of the [Sage-Bionetworks-Workflows](https://github.com/Sage-Bionetworks-Workflows) GitHub organization. These include the AWS credentials (_i.e._ access key IDs and secret access keys) for IAM users with permission to assume account-specific admin roles, which are used to provision resources.

The templates and configurations also leverage secrets stored in AWS Secrets Manager. These are retrieved using a [Sceptre resolver](https://github.com/iAnomaly/sceptre-resolver-aws-secrets-manager). Most of these secrets are created during deployment ([example](https://github.com/Sage-Bionetworks-Workflows/aws-workflows-nextflow-infra/blob/db37741e53fa5276b33b24d1af247d8d29bc0e56/templates/nextflow-tower-secret.yaml#L14-L34)), but the following were added manually:

- `nextflow/license`: The paid license key for Nextflow Tower
- `nextflow/github_oauth_app`: The GitHub OAuth client credentials

## Additional Notes

- The CIDR ranges of IP addresses specifies in the VPC configurations were added to the [Sage VPN](https://sagebionetworks.jira.com/wiki/spaces/IT/pages/352976898/Sage+VPN) table.

## License

This repository is licensed under the [Apache License 2.0](LICENSE).

Copyright 2021 Sage Bionetworks
