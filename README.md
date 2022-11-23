# Nextflow Infrastructure

The AWS infrastructure for hosting a private instance (see link below) of [Nextflow Tower](https://tower.nf/) and executing [Nextflow workflows](https://nextflow.io/) is defined in this repository and deployed using [CloudFormation](https://aws.amazon.com/cloudformation/) via [Sceptre](https://sceptre.cloudreach.com/).

The Nextflow infrastructure has been vetted by Sage IT to process sensitive or controlled-access (_e.g._ PHI) data. Notably, only [HIPAA eligible AWS services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/) are deployed.

## Access Tower

Click the link below and login with your `@sagebase.org` Google account:

<p align="center">➡️&ensp;<a href="https://tower.sagebionetworks.org/orgs/Sage-Bionetworks/workspaces" target="_blank" rel="noopener noreferrer"><b>Nextflow Tower</b> @ Sage Bionetworks</a>&ensp;⬅️</p>

## Getting Started

### Prospective Tower Users

Follow the [Tower User Onboarding](#tower-user-onboarding) instructions below. Access is currently restricted to Sage Bionetworks staff. **See [below](#getting-help) for how to get help if you run into any issues.**

### Prospective Contributors

Read through the [contribution guidelines](CONTRIBUTING.md) for more information. Contributions are welcome from anyone!

### Getting Help

Instructions on how to get help are described on the [Getting Started with Nextflow and Tower](https://sagebionetworks.jira.com/wiki/spaces/WF/pages/2191556616/Getting+Started+with+Nextflow+and+Tower#Getting-Help) page. This page is only accessible to Sage employees.

## Tower User Onboarding

Before you can use Nextflow Tower, you need to first deploy a Tower project, which consists of an encrypted S3 bucket and the IAM resources (_i.e._ users, roles, and policies) that Tower requires to access the encrypted bucket and execute the workflow on [AWS Batch](https://help.tower.nf/21.12/compute-envs/aws-batch/). Once these resources exist, they need to be configured in Nextflow Tower, which is a process that has been automated using CI/CD.

1. Create a 'stack name' by following this naming convention: concatenate a project name with the suffix `-project` (_e.g._ `imcore-project`, `amp-ad-project`, `commonmind-project`). Due to limits imposed by Tower, the stack name cannot contain more than 32 characters.

   **N.B.:** Anytime that `<stack_name>` appears below with the angle brackets, replace the placeholder with the actual stack name, omitting any angle brackets.

2. [Create an IT JIRA ticket](https://sagebionetworks.jira.com/jira/secure/CreateIssue.jspa?issuetype=3&pid=10083) requesting membership to the following JumpCloud groups for anyone who needs read/write or read-only access to the S3 bucket:

   - **For AMP-AD projects:** `strides-ampad-workflows-towerviewer`
   - **For all other projects:** `aws-workflow-nextflow-tower-viewer`

   To confirm whether you're already a member of these JumpCloud groups, you can expand the AWS Account list on [this page](https://d-906769aa66.awsapps.com/start#/) (after logging in with JumpCloud) and check if you have `TowerViewer` under `workflows-nextflow-prod`.

   ![AWS SSO Screenshot](assets/img/aws_sso.png)

3. Copy-paste the contents of [`config/projects-prod/example-project.yaml`](config/projects-prod/example-project.yaml) into a file called `<stack_name>.yaml`, which must be added to one of the following subdirectories:

   - **For AMP-AD projects:** `config/projects-ampad/`
   - **For all other projects:** `config/projects-prod/`

4. Follow the numbered steps listed in your new file. Note that some steps are required whereas others are optional.

   **N.B.** Here, read/write vs read-only access refers to the level of access granted to users for the encrypted S3 bucket and to the Tower workspace (more details below). **Given that access is granted to the entire bucket, you might want to create more specific Tower projects that provide more granular access control.**

5. Open a pull request (PR) on this repository with your new file. Once that's done, wait until someone reviews your PR. They will either request changes or merge the PR.

   **Getting Help:** If you are unfamiliar with Git/GitHub or don't know how to open a pull request, see [above](#getting-help) for how to get help.

6. Once the PR is merged, make sure that it was deployed successfully by reviewing the latest build on the [GitHub Actions](https://github.com/Sage-Bionetworks-Workflows/aws-workflows-nextflow-infra/actions?query=event%3Apush+branch%3Amain) page. This may take up to 20-30 minutes.

7. A successful deployment will result in the following changes:

   - Two S3 buckets were created or updated, each serving different purposes:

     - `s3://<stack_name>-tower-bucket/`: This bucket is intended for archival purposes, _i.e._ to store files in the long term. It can also be indexed by Synapse by default. Whenever you specify the `outdir` or `publishDir` parameters for a workflow, they should generally point to an S3 prefix in this bucket.
     - `s3://<stack_name>-tower-scratch/`: This bucket is intended to be used as scratch storage, _i.e._ to store files in the short term. The important difference with this bucket is that **files will automatically be deleted after 6 months.** This delay can be adjusted with the `ScratchLifecycleExpiration` parameter. This is intended as a convenience feature so users don't have to worry about cleaning up after themselves while benefitting from caching if the need arises (presumed here to be generally within 6 months). This bucket cannot be indexed by Synapse. It's ideal for storing the Nextflow work directories (configured on each compute environment by default) and for staging files from Synapse since they already exist somewhere else.

   - Users listed under `S3ReadWriteAccessArns` and `S3ReadOnlyAccessArns` in the YAML file were granted read/write and read-only access, respectively.

   - All users listed under `S3ReadWriteAccessArns` and `S3ReadOnlyAccessArns` were added to the Sage Bionetworks organization in Tower.

   - A new Tower workspace called `<stack_name>` was created under this organization.

   - Users listed under `S3ReadWriteAccessArns` were added to the workspace with the `Maintain` role, which grants the following permissions:

     > The users can launch pipeline and modify pipeline executions
       (e.g. can change the pipeline launch compute env, parameters,
       pre/post-run scripts, nextflow config) and create new pipeline
       configuration in the Launchpad. The users cannot modify Compute
       env settings and Credentials

   - Users listed under `S3ReadOnlyAccessArns` were added to the workspace with the `View` role, which grants the following permissions:

     > The users can access to the team resources in read-only mode

   - A set of AWS credentials called `<stack_name>` was added under this Tower workspace.

   - An AWS Batch compute environment called `<stack_name> (default)` was created using these credentials with a default configuration that should satisfy most use cases.

   **N.B.** If you need have special needs (_e.g._ higher vCPU limit, GPU-enabled instance types, NVMe storage), see [above](#getting-help) for how to contact the Tower administrators, who can create additional compute environments in your workspace.

8. Log into Nextflow Tower using the [link](#access-tower) at the top of this README and open your project workspace. As long as you were listed under `S3ReadWriteAccessArns`, then you'll be able to add pipelines to your workspace and launch them on your data.

9.  Check out the [Getting Started with Nextflow and Tower](https://sagebionetworks.jira.com/wiki/spaces/WF/pages/2191556616/Getting+Started+with+Nextflow+and+Tower) docs for additional instructions on how to launch workflows on Tower.

## License

This repository is licensed under the [Apache License 2.0](LICENSE).

Copyright 2022 Sage Bionetworks
