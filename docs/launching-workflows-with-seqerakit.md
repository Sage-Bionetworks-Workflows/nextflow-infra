# Launching Nextflow workflows programmatically with `seqerakit`

[`seqerakit`](https://github.com/seqeralabs/seqera-kit) is Seqera's official Python
wrapper around the [Seqera Platform CLI](https://github.com/seqeralabs/tower-cli) (`tw`).
It is the recommended way to launch and monitor workflows on Sage's Tower instance from
scripts or from an orchestrator such as Airflow, Prefect, Dagster, or Metaflow.

The workspaces, compute environments, and S3 buckets referenced below are the ones
provisioned by this repository (see [configure-tower-projects.py](configure-tower-projects.md)).

## Prerequisites

`seqerakit` shells out to the `tw` CLI, so both must be installed and on your `PATH`:

```bash
# 1. Install the Seqera Platform CLI (v0.11.0+). It is a single binary published on the
#    tower-cli releases page: https://github.com/seqeralabs/tower-cli/releases
#    Pick the asset for your machine: tw-osx-arm64 (Apple silicon), tw-osx-x86_64
#    (Intel Mac), or tw-linux-x86_64. Each release also has a checksums_sha256.txt.
TW_VERSION=v0.42.0
TW_ASSET=tw-osx-arm64
mkdir -p ~/.local/bin
curl -fL -o ~/.local/bin/tw \
    "https://github.com/seqeralabs/tower-cli/releases/download/${TW_VERSION}/${TW_ASSET}"
chmod +x ~/.local/bin/tw
export PATH="$HOME/.local/bin:$PATH"   # add this line to ~/.zshrc or ~/.bashrc to keep it
tw --version

# 2. Install seqerakit (Python 3.10+)
pip install seqerakit
# or, to keep it isolated from your project environment:
uv tool install seqerakit
```

Authenticate with a personal access token created under **Your tokens** in the Tower UI,
and point the CLI at Sage's Tower instance:

```bash
export TOWER_ACCESS_TOKEN='<your-tower-access-token>'

# Production
export TOWER_API_ENDPOINT='https://tower.sagebionetworks.org/api/'
# or, for the dev instance
export TOWER_API_ENDPOINT='https://tower-dev.sagebionetworks.org/api/'
```

Never commit or paste your access token anywhere shared. If one leaks, revoke it under
**Your tokens** in the Tower UI.

## Naming conventions

The names you pass to `tw` follow from the project stack name (_e.g._
`example-dev-project`, from `config/projects-*/example-dev-project.yaml`):

| Resource | Name |
| --- | --- |
| Workspace | `Sage-Bionetworks/<stack-name>` |
| Compute environment (spot) | `<stack-name>-spot-<CE_VERSION>` (_e.g._ `example-dev-project-spot-v13`) |
| Compute environment (on-demand) | `<stack-name>-ondemand-<CE_VERSION>` |
| Scratch bucket (work dir) | `s3://<stack-name>-tower-scratch` |

`CE_VERSION` is defined in [`bin/configure-tower-projects.py`](../bin/configure-tower-projects.py)
and changes when compute environments are rebuilt. To avoid hard-coding it, list what is
available in a workspace:

```bash
tw compute-envs list --workspace Sage-Bionetworks/example-dev-project
```

## Quick check: launching `nf-canary`

[`seqeralabs/nf-canary`](https://github.com/seqeralabs/nf-canary) is a small pipeline
that checks whether a compute environment works. It needs no inputs, so it's a good first
run to confirm that your token, endpoint, workspace, and compute environment are all set
up correctly:

```python
from seqerakit import seqeraplatform

tw = seqeraplatform.SeqeraPlatform(json=True)

result = tw.launch(
    "--workspace", "Sage-Bionetworks/example-dev-project",
    "--compute-env", "example-dev-project-spot-v13",
    "--name", "my-test",
    "--work-dir", "s3://example-dev-project-tower-scratch/work",
    "https://github.com/seqeralabs/nf-canary",
)
print(result["workflowUrl"])
```

On success, `result` looks like this:

```python
{
    "workflowId": "5UrutbeFgspgt4",
    "workflowUrl": "https://tower-dev.sagebionetworks.org/orgs/Sage-Bionetworks/workspaces/example-dev-project/watch/5UrutbeFgspgt4",
    "workspaceId": 126047213146763,
    "workspaceRef": "[Sage-Bionetworks / example-dev-project]",
}
```

### Common launch errors

`seqerakit` raises `ResourceNotFoundError` or `CommandError` with the error message from
`tw`. These are the ones you're most likely to see:

| Error from `tw` | Cause and fix |
| --- | --- |
| `Pipeline 'seqeralabs/nf-canary' not found` | `tw` treats a bare `org/repo` as the name of a pipeline saved in the workspace's **Launchpad**. To launch straight from GitHub, pass the full URL instead, _e.g._ `https://github.com/seqeralabs/nf-canary`. |
| `Run name must start with a letter, and contain a maximum of 80 alphanumeric characters separated by dashes or underscores` | `--name` can't contain spaces or other punctuation. Use _e.g._ `my-test` or `my_test`, not `my test`. |
| `Unknown pipeline profile: sage` | The pipeline doesn't define that profile. `sage` comes from nf-core's [institutional configs](https://github.com/nf-core/configs), so it only works with nf-core pipelines (_e.g._ `nf-core/rnaseq`). Leave out `--profile` for pipelines like `nf-canary`. |
| `/bin/sh: tw: command not found` | The `tw` CLI isn't on your `PATH`; see [Prerequisites](#prerequisites). |

## Launching a run from Python

The `SeqeraPlatform` object forwards any attribute to the corresponding `tw` subcommand,
so `tw.launch(...)` runs `tw launch ...` and returns its output:

```python
from seqerakit import seqeraplatform

# json=True makes every command return parsed JSON instead of raw stdout
tw = seqeraplatform.SeqeraPlatform(json=True)

result = tw.launch(
    "--workspace", "Sage-Bionetworks/example-dev-project",
    "--compute-env", "example-dev-project-spot-v13",
    "--name", "my_test_dataset_rnaseq",
    "--revision", "3.11.2",
    "--profile", "sage",
    "--work-dir", "s3://example-dev-project-tower-scratch/work",
    "--params-file", "rnaseq-params.yaml",
    "https://github.com/nf-core/rnaseq",
)

workflow_id = result["workflowId"]
print(f"Launched run: {workflow_id}")
```

Pipeline parameters go in the `--params-file` YAML:

```yaml
# rnaseq-params.yaml
input: s3://example-dev-project-tower-scratch/work/my_test_dataset.csv
outdir: s3://example-dev-project-tower-scratch/work/my_test_dataset_rnaseq
pseudo_aligner: salmon
skip_bbsplit: false
```

## Waiting for a run to finish

`tw launch --wait` blocks until the run reaches a given state. Valid states are
`SUBMITTED`, `RUNNING`, and `SUCCEEDED`; the command exits non-zero if the run fails
first.

```python
# Blocks until the run succeeds (or raises if it fails)
tw.launch(
    "--workspace", "Sage-Bionetworks/example-dev-project",
    "--compute-env", "example-dev-project-spot-v13",
    "--name", "my_test_dataset_rnaseq",
    "--wait", "SUCCEEDED",
    "https://github.com/nf-core/rnaseq",
)
```

For long-running pipelines you usually want to return control to your orchestrator
between checks instead of holding a blocking process open. Launch with
`--wait SUBMITTED`, then poll:

```python
import time

def monitor_workflow(tw, workspace, workflow_id, wait_time=300):
    """Poll a run until it reaches a terminal state; return that state."""
    terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"}
    while True:
        run = tw.runs("view", "--workspace", workspace, "--id", workflow_id)
        status = run["general"]["status"]
        if status in terminal:
            return status
        time.sleep(wait_time)

status = monitor_workflow(tw, "Sage-Bionetworks/example-dev-project", workflow_id)
if status != "SUCCEEDED":
    raise RuntimeError(f"Workflow did not complete successfully ({status}).")
```

In Airflow, Prefect, or Dagster, prefer that pattern split across two tasks — a launch
task that returns the workflow ID and a deferrable sensor task that checks status — so a
scheduler restart does not lose the run.

## Declarative alternative (YAML)

`seqerakit` can also drive everything from a YAML file, which is convenient when the run
configuration is checked into a repository rather than computed at runtime:

```yaml
# rnaseq-launch.yaml
launch:
  - name: 'my_test_dataset_rnaseq'
    workspace: 'Sage-Bionetworks/example-dev-project'
    compute-env: 'example-dev-project-spot-v13'
    pipeline: 'https://github.com/nf-core/rnaseq'
    revision: '3.11.2'
    profile: 'sage'
    work-dir: 's3://example-dev-project-tower-scratch/work'
    params:
      input: 's3://example-dev-project-tower-scratch/work/my_test_dataset.csv'
      outdir: 's3://example-dev-project-tower-scratch/work/my_test_dataset_rnaseq'
```

```bash
seqerakit rnaseq-launch.yaml --dryrun   # print the tw commands without running them
seqerakit rnaseq-launch.yaml            # actually launch
```

## Further reading

- [seqerakit documentation](https://github.com/seqeralabs/seqera-kit)
- [Seqera Platform CLI (`tw`) documentation](https://docs.seqera.io/platform-cli)
- [Seqera Platform REST API](https://docs.seqera.io/platform-cloud/api/overview), for
  anything neither the CLI nor `seqerakit` exposes
