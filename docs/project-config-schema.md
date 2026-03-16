# Project Configuration File Schema

Project configuration files are YAML files that define Seqera Tower (Nextflow Tower)
workspaces, users, compute environments, and associated AWS resources. They are
processed by `bin/configure-tower-projects.py`.

## File Naming & Location

- Files must end with `-project.yaml` (e.g., `my-team-project.yaml`)
- Placed in a project config directory (e.g., `config/projects-prod/`)

## Attributes

### `stack_name` (required)

Unique identifier for the project. Used as the workspace name in Tower and the
CloudFormation stack name. Must not exceed 32 characters.

```yaml
stack_name: my-team-project
```

### `template` (required)

Specifies the CloudFormation template to use. Must reference `tower-project.j2`.

```yaml
template:
  path: tower-project.j2
```

### `parameters` (required)

CloudFormation stack parameters. Must contain at least one of `S3ReadWriteAccessArns`
or `S3ReadOnlyAccessArns`.

```yaml
parameters:
  S3ReadWriteAccessArns:
    - '{{stack_group_config.tower_viewer_arn_prefix}}/[email]@sagebase.org'
  S3ReadOnlyAccessArns:
    - '{{stack_group_config.tower_viewer_arn_prefix}}/[email]@sagebase.org'
```

| Parameter | Description |
|---|---|
| `S3ReadWriteAccessArns` | List of assumed-role ARNs. Emails are extracted and mapped to Tower `maintain` role. |
| `S3ReadOnlyAccessArns` | List of assumed-role ARNs. Emails are extracted and mapped to Tower `view` role. |
| `AllowSynapseIndexing` | `Enabled` or `Disabled`. Controls Synapse indexing on the archival S3 bucket. |
| `EnableScratchDataExpiration` | `Enabled` or `Disabled`. Controls data lifecycle on the scratch S3 bucket. |
| `ScratchLifecycleTransition` | Number of days before transitioning scratch data (e.g., `'30'`). |
| `ScratchLifecycleStorageClass` | Storage class for transitioned data (e.g., `INTELLIGENT_TIERING`). |
| `ScratchLifecycleExpiration` | Number of days before scratch data is deleted (e.g., `'183'`). |
| `AccountAdminArns` | List of admin role ARNs (typically SSO admin and CI/CD roles). |
| `TemplateRootUrl` | S3 URL for CloudFormation templates. |
| `TowerForgePolicyArn` | ARN of the Nextflow Forge IAM policy (from dependency stack). |
| `TowerLaunchPolicyArn` | ARN of the Nextflow Launch IAM policy (from dependency stack). |

### `stack_tags` (optional)

AWS resource tags applied to the CloudFormation stack. A `TowerProject` tag is
automatically added with the `stack_name` value. The `CostCenter` value is
automatically trimmed to just the program code portion.

```yaml
stack_tags:
  Department: TECH
  Project: Infrastructure
  OwnerEmail: [email]@sagebase.org
  CostCenter: Program Name / 312100
```

Tag values are sanitized: any characters outside `[A-z0-9_-]` are replaced with `_`.

### `dependencies` (optional)

List of Sceptre stack dependencies that must be deployed before this stack.

```yaml
dependencies:
  - common/nextflow-forge-iam-policy.yaml
  - common/nextflow-launch-iam-policy.yaml
```

### `sceptre_user_data` (optional)

Custom data passed to the Sceptre template. Currently supports:

#### `ManualComputeEnvs`

List of manual compute environments that reference existing Batch Forge CEs in
other workspaces. When specified, the workspace uses these manual CEs instead of
creating its own Batch Forge CEs.

```yaml
sceptre_user_data:
  ManualComputeEnvs:
    - WorkspaceName: shared-ce-prod-project
      ComputeEnvName: shared-ce-prod-project-ondemand-v13
    - WorkspaceName: shared-ce-prod-project
      ComputeEnvName: shared-ce-prod-project-spot-v13
```

| Field | Description |
|---|---|
| `WorkspaceName` | Name of the workspace containing the source Batch Forge CE. |
| `ComputeEnvName` | Name of the source compute environment to reference. |

### `ignore` (optional)

When set to a truthy value, the project is skipped during processing. Accepts:
`true`, `True`, `"true"`, `"yes"`, `"1"`.

```yaml
ignore: true
```

## Compute Environment Behavior

- If a workspace has users with `launch` (or higher) permissions and no
  `ManualComputeEnvs` configured, two Batch Forge CEs are automatically created:
  `{stack_name}-spot-{CE_VERSION}` and `{stack_name}-ondemand-{CE_VERSION}`.
- If `ManualComputeEnvs` is configured, manual CEs referencing the specified
  source CEs are created instead.
- If no users have launch permissions, no CEs are created and existing CEs are
  cleaned up.

## Minimal Example

```yaml
stack_name: my-team-project

template:
  path: tower-project.j2

parameters:
  S3ReadWriteAccessArns:
    - '{{stack_group_config.tower_viewer_arn_prefix}}/[email]@sagebase.org'
  AccountAdminArns:
    - '{{stack_group_config.sso_admin_role.arn}}'
  TemplateRootUrl: 'https://{{stack_group_config.admincentral_cf_bucket}}.s3.amazonaws.com'
  TowerForgePolicyArn: !stack_output_external nextflow-forge-iam-policy::NextFlowForgePolicyArn
  TowerLaunchPolicyArn: !stack_output_external nextflow-launch-iam-policy::NextFlowLaunchPolicyArn

dependencies:
  - common/nextflow-forge-iam-policy.yaml
  - common/nextflow-launch-iam-policy.yaml
  - projects-prod/shared-ce-prod-project.yaml

stack_tags:
  Department: TECH
  Project: Infrastructure
  OwnerEmail: [email]@sagebase.org
  CostCenter: NO PROGRAM / 000000
```
