# configure-tower-projects.py

A Python script that synchronizes Seqera Tower (Nextflow Tower) workspaces with
project configuration files. It creates and manages Tower organizations, workspaces,
users, compute environments, and credentials.

## Prerequisites

### CloudFormation Stacks

Before running this script, the project configuration files must be deployed as
CloudFormation stacks using Sceptre. The script reads stack outputs (S3 buckets,
IAM roles, etc.) that are created by these stacks.

```bash
# Deploy all project stacks
pipenv run sceptre launch config/projects-prod
```

### Python Dependencies

Install dependencies using pipenv:

```bash
pipenv install
```

Key dependencies:
- `boto3` - AWS SDK for Python
- `pyyaml` - YAML parsing
- `sagetasks` - Provides `TowerClient` for Tower API interactions

### Environment Variables

The script requires the following environment variables:

| Variable | Description |
|---|---|
| `TOWER_ACCESS_TOKEN` | Seqera Tower API access token |
| `AWS_ACCESS_KEY_ID` | AWS credentials (or use AWS profile/role) |
| `AWS_SECRET_ACCESS_KEY` | AWS credentials (or use AWS profile/role) |
| `AWS_DEFAULT_REGION` | AWS region (defaults to `us-east-1`) |

### AWS Permissions

The script requires AWS permissions to:
- Describe CloudFormation stacks (to retrieve stack outputs)
- Read Secrets Manager secrets (for Tower Forge credentials)

### Tower Permissions

The Tower access token must have organization admin permissions to:
- Create/manage workspaces
- Add/remove participants
- Create/manage compute environments
- Create/manage credentials

## Usage

```bash
pipenv run python bin/configure-tower-projects.py <projects_dir> [options]
```

### Arguments

| Argument | Description |
|---|---|
| `projects_dir` | Path to directory containing project configuration files |

### Options

| Option | Description |
|---|---|
| `--dry_run`, `-n` | Validate configs without making changes to Tower |
| `--debug`, `-d` | Enable debug mode for API requests |

### Examples

Validate project configurations (dry run):

```bash
pipenv run python bin/configure-tower-projects.py config/projects-prod --dry_run
```

Sync all projects to Tower:

```bash
pipenv run python bin/configure-tower-projects.py config/projects-prod
```

Enable debug output:

```bash
pipenv run python bin/configure-tower-projects.py config/projects-prod --debug
```

## What the Script Does

For each valid project configuration file in the specified directory:

1. **Organization Setup**
   - Creates or retrieves the Tower organization ("Sage Bionetworks")
   - Adds users as organization members

2. **Workspace Creation**
   - Creates a workspace for each project (named after `stack_name`)
   - Retrieves CloudFormation stack outputs for AWS resource references

3. **User Management**
   - Extracts user emails from S3 access ARNs in the config
   - Adds users as workspace participants with appropriate roles
   - Removes participants not in the config
   - Maps `S3ReadWriteAccessArns` users to Tower `maintain` role
   - Maps `S3ReadOnlyAccessArns` users to Tower `view` role
   - If all users are mapped to `view` only (no launchers), compute environments
     in the workspace will be deactivate and deleted to free up AWS Batch CE
     capacity

   > [!CAUTION]
   > If you are using shared compute environments, do not deactivate your workspace
     doing so will delete the shared compute environment and affect other workspaces
     that depend on it.

4. **Compute Environment Management**
   - Cleans up old compute environments (not matching current `CE_VERSION`)
   - For workspaces with launchers:
     - If `ManualComputeEnvs` is configured: creates manual CEs referencing source CEs
     - Otherwise: creates Batch Forge CEs (SPOT and on-demand)
   - Sets the primary compute environment

5. **Credentials Management**
   - Creates AWS credentials for Batch Forge using secrets from AWS Secrets Manager

6. **Resource Labels**
   - Creates resource labels from `stack_tags` for compute environment tagging

## Compute Environment Versioning

The script uses `CE_VERSION` (i.e. `v13`) to track compute environment versions.
When updating CE configurations:

1. Increment `CE_VERSION` in the script
2. Run the script to create new CEs with the updated version
3. Old CEs (not matching the version) are automatically cleaned up

## Skipping Projects

To temporarily skip a project without removing its config file, add `ignore: true`.
This is useful when you want to pause Tower provisioning for a project while
keeping its configuration for future use.  You must remember to disable
this when you want the workspace to receive updates again.

```yaml
ignore: true
stack_name: my-project
# ... rest of config
```

## Troubleshooting

### 409 Conflict Error

If you see `409 Client Error: Conflict`, a compute environment with the same name
already exists. The script checks for existing CEs before creation, but race
conditions or manual changes can cause conflicts.

### Missing Workspace

If a workspace lookup fails, ensure:
- The CloudFormation stack exists and is in a complete state
- The `stack_name` matches the expected workspace name

### Authentication Errors

Verify:
- `TOWER_ACCESS_TOKEN` is set and valid
- AWS credentials are configured correctly
- The Tower token has sufficient permissions

## Related Documentation

- [Project Configuration Schema](project-config-schema.md) - Config file format
- [Seqera Tower API](https://tower.nf/openapi/) - Tower API reference
