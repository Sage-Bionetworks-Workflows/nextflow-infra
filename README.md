# Nextflow Workflows Infrastructure

The AWS infrastructure for hosting a private instance of [Nextflow Tower](https://tower.nf/) and executing [Nextflow workflows](https://nextflow.io/) is defined in this repository and deployed using [CloudFormation](https://aws.amazon.com/cloudformation/) via [Sceptre](https://sceptre.cloudreach.com/).

## AWS Accounts

Two AWS accounts are managed by this repository, both of which were [bootstrapped](https://sagebionetworks.jira.com/wiki/spaces/IT/pages/2058878986/Bootstrapping+AWS+Project+Accounts) using [org-formation](https://github.com/org-formation/org-formation-cli). They are defined in this [organization.yaml](https://github.com/Sage-Bionetworks-IT/organizations-infra/blob/master/org-formation/organization.yaml) file. The two accounts are:

- `workflows-nextflow-prod` for production use
- `workflows-nextflow-dev` for testing purposes

### Role-Based Access

Human access to these AWS accounts (programmatically or via the Management Console) is provided using IAM roles defined in [organizations-infra](https://github.com/Sage-Bionetworks-IT/organizations-infra/blob/master/org-formation/700-aws-sso/_tasks.yaml) (search for "WorkflowsNextflow"). These roles are individually [bound](https://github.com/Sage-Bionetworks-IT/organizations-infra/blob/master/org-formation/700-aws-sso/README.md) to user groups in JumpCloud, which are managed by Sage IT.

- **Viewer:** [`ViewOnlyAccess`](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_job-functions.html#jf_view-only-user)
- **Developer-IAM-Contrained:** [`PowerUserAccess`](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_job-functions.html#jf_developer-power-user) and contrained IAM access, namely only to resources prefixed with `dev-`
- **Administrator:** [`AdministratorAccess`](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_job-functions.html#jf_administrator)

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
