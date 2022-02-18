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

Message us in the [`#workflow_users`](https://sagebionetworks.slack.com/archives/C8SJHFCKT) Slack channel or email us at `nextflow-admins[at]sagebase[dot]org`.

## Tower User Onboarding

Before you can use Nextflow Tower, you need to first deploy a Tower project, which consists an encrypted S3 bucket and the IAM resources (_i.e._ users, roles, and policies) that Tower requires to access the encrypted bucket and execute the workflow on [AWS Batch](https://help.tower.nf/compute-envs/aws-batch/). Once these resources exist, they need to be configured in Nextflow Tower, which is a process that has been automated using CI/CD.

1. Determine what is known as the stack name by concatenating the project name with the suffix `-project` (_e.g._ `imcore-project`, `amp-ad-project`, `commonmind-project`).

   **N.B.:** Anytime that `<stack_name>` appears below with the angle brackets, replace the placeholder with the actual stack name, omitting any angle brackets.

2. [Create](https://sagebionetworks.jira.com/jira/software/c/projects/IT/issues/) an IT JIRA ticket requesting membership to the following JumpCloud groups for anyone who needs read/write or read-only access to the S3 bucket:

   - `aws-sandbox-developers`
   - `aws-workflow-nextflow-tower-viewer`

   To confirm whether you're already a member of these JumpCloud groups, you can expand the AWS Account list on [this page](https://d-906769aa66.awsapps.com/start#/) (after logging in with JumpCloud) and check if you have `Developer` listed under `org-sagebase-sandbox` and `TowerViewer` under `workflows-nextflow-dev` and `workflows-nextflow-prod`.

   ![AWS SSO Screenshot](assets/img/aws_sso.png)

3. Open a pull request on this repository in which you duplicate [`config/projects/example-project.yaml`](config/projects-prod/example-project.yaml) as `<stack_name>.yaml` in the `projects/` subdirectory and then follow the numbered steps listed in the file. Note that some steps are required whereas others are optional.

   **N.B.** Here, read/write vs read-only access refers to the level of access granted to users for the encrypted S3 bucket and to the Tower workspace (more details below). **Given that access is granted to the entire bucket, you might want to create more specific Tower projects that provide more granular access control.**

   **Getting Help:** If you are unfamiliar with Git/GitHub or don't know how to open a pull request, see [above](#getting-help) for how to get help.

4. Once the pull request is approved and merged, [confirm](https://github.com/Sage-Bionetworks-Workflows/aws-workflows-nextflow-infra/actions?query=event%3Apush+branch%3Amain) that your PR was deployed successfully. If so, the following happened on your behalf:

   - An S3 bucket called `s3://<stack_name>-tower-bucket/` was created, and users listed under `S3ReadWriteAccessArns` and `S3ReadOnlyAccessArns` have read/write and read-only access, respectively.

   - All users listed under `S3ReadWriteAccessArns` and `S3ReadOnlyAccessArns` were added to the Sage Bionetworks organization in Tower.

   - A new Tower workspace called `<stack_name>` was created under this organization.

   - Users listed under `S3ReadWriteAccessArns` were added as workspace participants with the `Maintain` role, which grants the following permissions:

     > The users can launch pipeline and modify pipeline executions
       (e.g. can change the pipeline launch compute env, parameters,
       pre/post-run scripts, nextflow config) and create new pipeline
       configuration in the Launchpad. The users cannot modify Compute
       env settings and Credentials

   - Users listed under `S3ReadOnlyAccessArns` were added as workspace participants with the `View` role, which grants the following permissions:

     > The users can access to the team resources in read-only mode

   - A set of AWS credentials called `<stack_name>` was added under this Tower workspace.

   - An AWS Batch compute environment called `<stack_name> (default)` was created using these credentials with a default configuration that should satisfy most use cases.

   **N.B.** If you need have special needs (_e.g._ more CPUs, on-demand EC2 instances, FSx for Lustre), see [above](#getting-help) for how to contact the administrators, who can create additional compute environments in your workspace.

5. Log into Nextflow Tower using the [link](#access-nextflow-tower) at the top of this README and open your project workspace. If you were listed under `S3ReadWriteAccessArns`, then you'll be able to add pipelines to your workspace and launch them on your data.

6. Make sure that this [Confluence wiki page](https://sagebionetworks.jira.com/l/c/1hm4NP7a) is watched by everyone who will be running workflows on Tower. This generally doesn't need to include individuals listed as view-only in the `<stack_name>.yaml` file.

   **N.B.** To obtain a list of current watchers and to add new watchers, click the "Manage watchers" button under the 👁 (eye) icon at the top right of the Confluence page.

7. Read through the "Usage Details" and "Scheduled Downtime" sections on the wiki page. Any important updates to this page will be shared with watchers.

## License

This repository is licensed under the [Apache License 2.0](LICENSE).

Copyright 2021 Sage Bionetworks
