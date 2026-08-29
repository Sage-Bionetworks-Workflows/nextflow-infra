#!/usr/bin/env python3

"""Look up (and optionally delete) orphaned AWS Batch compute environments.

An *orphaned* AWS Batch compute environment (CE) is one that is NOT managed
by an existing Seqera Tower Batch Forge compute environment.

How the link works
------------------
Tower's Batch Forge names the AWS resources it creates after the Tower
compute environment ID:

    AWS Batch compute environment:  TowerForge-<towerComputeEnvId>-head
    AWS Batch job queue:            TowerForge-<towerComputeEnvId>-work

So a Forge-managed Batch CE embeds its Tower CE ID in its name. A Batch CE
is orphaned when either:

  * its name matches ``TowerForge-<id>-...`` but that ``<id>`` no longer
    corresponds to a live Tower compute environment (the Tower CE was
    deleted but the AWS resources were left behind), OR
  * its name does not match the Forge pattern at all (not created/managed
    by a Tower Forge CE).

Both cases mean "not managed by an existing Tower Forge CE", which is the
definition of orphaned for this tool.

The report lists, for both orphaned and non-orphaned Batch CEs, the CE name
and its ``TowerProject`` tag (the tag Forge propagates from the Tower
resource label of the same name).

Usage
-----
    # Report only (read-only)
    pipenv run python temp/orphaned-batch-ce-tool.py \
        [--profile AWS_PROFILE] [--region us-east-1] \
        [--endpoint TOWER_URL] [--token TOWER_TOKEN] [--json]

    # Delete the orphaned CEs (prompts unless --yes)
    pipenv run python temp/orphaned-batch-ce-tool.py --profile AWS_PROFILE --delete
    pipenv run python temp/orphaned-batch-ce-tool.py --profile AWS_PROFILE --delete --yes
    pipenv run python temp/orphaned-batch-ce-tool.py --profile AWS_PROFILE --delete --dry-run

The Tower token is read from --token or $TOWER_ACCESS_TOKEN (falling back to
$TOWER_TOKEN, then $NXF_TOWER_TOKEN). Get one from <endpoint>/tokens.

Without --delete the tool is READ-ONLY. With --delete it disables and
deletes each orphaned CE and its associated job queues -- a destructive,
non-reversible operation, so it confirms first unless --yes is given.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Set

import boto3  # type: ignore
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore

DEFAULT_ENDPOINT = "https://tower-dev.sagebionetworks.org"
DEFAULT_REGION = "us-east-1"
TIMEOUT = 30
TOWER_PROJECT_TAG = "TowerProject"

# Batch Forge names the compute environment "TowerForge-<id>-<suffix>".
FORGE_NAME_RE = re.compile(r"^TowerForge-(?P<ce_id>[^-]+)-.+$")

# Job-queue deletion polling (queues must be gone before the CE can delete).
QUEUE_DELETE_POLL_SECONDS = 5
QUEUE_DELETE_POLL_MAX = 60  # up to ~5 minutes

# Compute-environment state polling. A CE must finish transitioning to a
# settled DISABLED state before it can be deleted; disabling is async.
CE_STATE_POLL_SECONDS = 5
CE_STATE_POLL_MAX = 60  # up to ~5 minutes

# Job-queue state polling. Like a CE, a queue must reach a settled DISABLED
# state before it can be deleted; update_job_queue is async.
QUEUE_STATE_POLL_SECONDS = 5
QUEUE_STATE_POLL_MAX = 60  # up to ~5 minutes


class TowerError(Exception):
    """Raised when the Tower API returns an unexpected response."""


class TowerClient:
    """Minimal, read-only Tower API client built on the standard library."""

    def __init__(self, endpoint: str, token: str) -> None:
        endpoint = endpoint.rstrip("/")
        if endpoint.endswith("/api"):
            endpoint = endpoint[: -len("/api")]
        self.endpoint = endpoint
        self.base_url = f"{endpoint}/api"
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                body = response.read()
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:300]
            if err.code == 401:
                raise TowerError(
                    "401 Unauthorized: the token is invalid or expired. "
                    f"Get a new one from {self.endpoint}/tokens"
                ) from err
            if err.code == 403:
                raise TowerError(
                    f"403 Forbidden: the token lacks permission for {method} {path}."
                ) from err
            raise TowerError(
                f"{err.code} {err.reason} for {method} {path}: {detail}"
            ) from err
        except urllib.error.URLError as err:
            raise TowerError(
                f"Could not reach {url}: {err.reason}. Check the --endpoint value."
            ) from err
        if not body:
            return {}
        try:
            return json.loads(body)
        except ValueError as err:
            snippet = body.decode("utf-8", "replace")[:300]
            raise TowerError(
                f"Non-JSON response for {method} {path}: {snippet}"
            ) from err

    def list_orgs(self) -> List[Dict[str, Any]]:
        return self.request("GET", "/orgs").get("organizations", []) or []

    def list_workspaces(self, org_id: int) -> List[Dict[str, Any]]:
        response = self.request("GET", f"/orgs/{org_id}/workspaces")
        return response.get("workspaces", []) or []

    def list_compute_envs(self, workspace_id: int) -> List[Dict[str, Any]]:
        response = self.request(
            "GET", "/compute-envs", params={"workspaceId": workspace_id}
        )
        return response.get("computeEnvs", []) or []

    def collect_live_ce_ids(self, verbose: bool = True) -> Set[str]:
        """Return the set of live Tower compute environment IDs.

        Walks every org and workspace the token can see.
        """
        ce_ids: Set[str] = set()
        orgs = self.list_orgs()
        if not orgs:
            raise TowerError("No organizations found for this token.")
        for org in orgs:
            org_id = org["orgId"]
            org_name = org.get("name", "Unknown")
            for workspace in self.list_workspaces(org_id):
                ws_id = workspace["id"]
                ws_name = workspace.get("name", "Unknown")
                compute_envs = self.list_compute_envs(ws_id)
                for ce in compute_envs:
                    ce_ids.add(ce["id"])
                if verbose:
                    print(
                        f"  Tower: org '{org_name}' / workspace '{ws_name}' "
                        f"(ID: {ws_id}): {len(compute_envs)} compute env(s)"
                    )
        return ce_ids


class BatchClient:
    """Thin wrapper around the AWS Batch API (boto3)."""

    def __init__(self, profile: Optional[str], region: str) -> None:
        session = boto3.session.Session(profile_name=profile, region_name=region)
        self.client = session.client("batch")

    def list_compute_envs(self) -> List[Dict[str, Any]]:
        paginator = self.client.get_paginator("describe_compute_environments")
        envs: List[Dict[str, Any]] = []
        for page in paginator.paginate():
            envs.extend(page.get("computeEnvironments", []))
        return envs

    def find_associated_job_queues(self, ce_arn: str, ce_name: str) -> List[str]:
        """Return names of job queues that reference the given CE."""
        paginator = self.client.get_paginator("describe_job_queues")
        queues: List[str] = []
        for page in paginator.paginate():
            for queue in page.get("jobQueues", []):
                order = queue.get("computeEnvironmentOrder", [])
                referenced = {entry.get("computeEnvironment") for entry in order}
                if ce_arn in referenced or ce_name in referenced:
                    queues.append(queue["jobQueueName"])
        return queues

    def disable_job_queue(self, name: str) -> None:
        self.client.update_job_queue(jobQueue=name, state="DISABLED")

    def delete_job_queue(self, name: str) -> None:
        self.client.delete_job_queue(jobQueue=name)

    def describe_job_queue(self, name: str) -> Optional[Dict[str, Any]]:
        """Return the job queue description, or None if it no longer exists."""
        response = self.client.describe_job_queues(jobQueues=[name])
        queues = response.get("jobQueues", [])
        return queues[0] if queues else None

    def job_queue_exists(self, name: str) -> bool:
        return self.describe_job_queue(name) is not None

    def wait_until_queue_disabled(self, name: str) -> bool:
        """Block until the job queue is DISABLED and settled (status VALID).

        A queue must be state=DISABLED and NOT mid-update before it can be
        deleted; update_job_queue returns before the transition completes, so
        we poll. Returns True once ready, False on timeout.
        """
        for _ in range(QUEUE_STATE_POLL_MAX):
            queue = self.describe_job_queue(name)
            if queue is None:
                # Already gone -- nothing left to delete.
                return True
            state = queue.get("state")
            status = queue.get("status")
            if state == "DISABLED" and status == "VALID":
                return True
            if status == "INVALID":
                # An INVALID queue can still be deleted; stop waiting.
                return True
            time.sleep(QUEUE_STATE_POLL_SECONDS)
        return False

    def disable_compute_env(self, name: str) -> None:
        self.client.update_compute_environment(
            computeEnvironment=name, state="DISABLED"
        )

    def describe_compute_env(self, name: str) -> Optional[Dict[str, Any]]:
        """Return the CE description, or None if it no longer exists."""
        response = self.client.describe_compute_environments(computeEnvironments=[name])
        envs = response.get("computeEnvironments", [])
        return envs[0] if envs else None

    def wait_until_disabled(self, name: str) -> bool:
        """Block until the CE is DISABLED and settled (status VALID).

        A CE must be state=DISABLED and NOT mid-update before it can be
        deleted; update_compute_environment returns before the transition
        completes, so we poll. Returns True once ready, False on timeout or
        an invalid status.
        """
        for _ in range(CE_STATE_POLL_MAX):
            env = self.describe_compute_env(name)
            if env is None:
                # Already gone -- nothing left to delete.
                return True
            state = env.get("state")
            status = env.get("status")
            if state == "DISABLED" and status == "VALID":
                return True
            if status == "INVALID":
                # An INVALID CE can still be deleted; stop waiting.
                return True
            time.sleep(CE_STATE_POLL_SECONDS)
        return False

    def delete_compute_env(self, name: str) -> None:
        self.client.delete_compute_environment(computeEnvironment=name)


def classify(
    batch_envs: List[Dict[str, Any]], live_ce_ids: Set[str]
) -> Dict[str, List[Dict[str, Any]]]:
    """Split Batch CEs into 'orphaned' and 'managed' (not orphaned).

    A CE is managed only when it is Forge-named AND its embedded Tower CE ID
    is still live. Everything else is orphaned (Forge-named but gone from
    Tower, or not Forge-named at all).
    """
    orphaned: List[Dict[str, Any]] = []
    managed: List[Dict[str, Any]] = []
    for env in batch_envs:
        name = env.get("computeEnvironmentName", "")
        tags = env.get("tags", {}) or {}
        match = FORGE_NAME_RE.match(name)
        ce_id = match.group("ce_id") if match else None
        record = {
            "name": name,
            "arn": env.get("computeEnvironmentArn"),
            "status": env.get("status"),
            "state": env.get("state"),
            "towerProject": tags.get(TOWER_PROJECT_TAG),
            "towerComputeEnvId": ce_id,
            "forgeManaged": ce_id is not None,
        }
        if ce_id is not None and ce_id in live_ce_ids:
            managed.append(record)
        else:
            orphaned.append(record)
    return {"orphaned": orphaned, "managed": managed}


def print_record_table(records: List[Dict[str, Any]]) -> None:
    if not records:
        print("  (none)")
        return
    name_width = max(len(r["name"]) for r in records)
    name_width = min(max(name_width, 4), 60)
    header = f"  {'NAME'.ljust(name_width)}  {TOWER_PROJECT_TAG}"
    print(header)
    print(f"  {'-' * name_width}  {'-' * len(TOWER_PROJECT_TAG)}")
    for record in records:
        project = record["towerProject"] if record["towerProject"] else "(no tag)"
        print(f"  {record['name'].ljust(name_width)}  {project}")


def delete_orphan(batch: BatchClient, record: Dict[str, Any], verbose: bool) -> bool:
    """Disable and delete one orphaned CE and its job queues.

    Returns True on success, False on failure. Never raises.
    """
    name = record["name"]
    arn = record["arn"] or name
    try:
        # Job queues must be disabled + deleted before the CE can be deleted.
        queues = batch.find_associated_job_queues(arn, name)
        for queue in queues:
            if verbose:
                print(f"    disabling job queue: {queue}")
            batch.disable_job_queue(queue)
        # Disabling is async: a queue must reach a settled DISABLED state
        # before delete_job_queue will succeed, otherwise AWS returns
        # "Cannot delete, resource is being modified."
        for queue in queues:
            if verbose:
                print(f"    waiting for job queue to disable: {queue}")
            if not batch.wait_until_queue_disabled(queue):
                print(
                    f"    ! job queue {queue} did not reach a settled DISABLED "
                    "state in time; skipping CE delete. Re-run later to finish."
                )
                return False
        for queue in queues:
            if verbose:
                print(f"    deleting job queue: {queue}")
            batch.delete_job_queue(queue)
        # Wait for queues to actually disappear.
        for queue in queues:
            for _ in range(QUEUE_DELETE_POLL_MAX):
                if not batch.job_queue_exists(queue):
                    break
                time.sleep(QUEUE_DELETE_POLL_SECONDS)
            else:
                print(
                    f"    ! job queue {queue} still exists after waiting; "
                    "skipping CE delete to avoid an error."
                )
                return False

        if verbose:
            print(f"    disabling compute environment: {name}")
        batch.disable_compute_env(name)
        # A CE must reach a settled DISABLED state before it can be deleted;
        # the disable call is async, so poll until it transitions.
        if verbose:
            print("    waiting for compute environment to disable...")
        if not batch.wait_until_disabled(name):
            print(
                f"    ! {name} did not reach a settled DISABLED state in time; "
                "skipping delete. Re-run later to finish."
            )
            return False

        if verbose:
            print(f"    deleting compute environment: {name}")
        batch.delete_compute_env(name)
        return True
    except (BotoCoreError, ClientError) as err:
        print(f"    x failed to delete {name}: {err}")
        return False


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Look up (and optionally delete) orphaned AWS Batch compute "
        "environments not managed by an existing Seqera Tower Forge CE."
    )
    parser.add_argument(
        "--profile",
        default=os.environ.get("AWS_PROFILE"),
        help="AWS profile to use (default: $AWS_PROFILE or the default chain)",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", DEFAULT_REGION),
        help=f"AWS region (default: {DEFAULT_REGION})",
    )
    parser.add_argument(
        "--endpoint",
        default=(
            os.environ.get("TOWER_API_ENDPOINT")
            or os.environ.get("NXF_TOWER_API_URL")
            or DEFAULT_ENDPOINT
        ),
        help=(
            f"Tower endpoint (default: $TOWER_API_ENDPOINT, "
            f"$NXF_TOWER_API_URL, or {DEFAULT_ENDPOINT})"
        ),
    )
    parser.add_argument(
        "--token",
        default=(
            os.environ.get("TOWER_ACCESS_TOKEN")
            or os.environ.get("TOWER_TOKEN")
            or os.environ.get("NXF_TOWER_TOKEN")
        ),
        help=(
            "Tower API token (default: $TOWER_ACCESS_TOKEN, $TOWER_TOKEN, "
            "or $NXF_TOWER_TOKEN)"
        ),
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete the orphaned compute environments (destructive)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt when using --delete",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --delete, show what would be deleted without deleting",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a text report",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)

    if not args.token:
        print(
            "Error: no Tower token provided. Pass --token or set "
            "TOWER_ACCESS_TOKEN, TOWER_TOKEN, or NXF_TOWER_TOKEN.\n"
            f"Get a token from {args.endpoint.rstrip('/')}/tokens",
            file=sys.stderr,
        )
        return 2

    verbose = not args.json

    if verbose:
        print("Orphaned AWS Batch Compute Environment Tool")
        print("===========================================")
        print(f"AWS profile:    {args.profile or '(default chain)'}")
        print(f"AWS region:     {args.region}")
        print(f"Tower endpoint: {args.endpoint}")
        print()
        print("Listing AWS Batch compute environments...")

    try:
        batch = BatchClient(args.profile, args.region)
        batch_envs = batch.list_compute_envs()
    except (BotoCoreError, ClientError) as err:
        print(f"Error listing AWS Batch compute environments: {err}", file=sys.stderr)
        return 1
    if verbose:
        print(f"  Found {len(batch_envs)} AWS Batch compute environment(s)")
        print()
        print("Collecting live Seqera Tower compute environments...")

    tower = TowerClient(args.endpoint, args.token)
    try:
        live_ce_ids = tower.collect_live_ce_ids(verbose=verbose)
    except TowerError as err:
        print(f"Error querying Seqera Tower: {err}", file=sys.stderr)
        return 1
    if verbose:
        print(f"  Found {len(live_ce_ids)} live Tower compute environment(s)")
        print()

    groups = classify(batch_envs, live_ce_ids)
    orphaned = groups["orphaned"]
    managed = groups["managed"]

    if args.json:
        json.dump(
            {
                "region": args.region,
                "counts": {
                    "batch_total": len(batch_envs),
                    "tower_live": len(live_ce_ids),
                    "orphaned": len(orphaned),
                    "not_orphaned": len(managed),
                },
                "orphaned": orphaned,
                "not_orphaned": managed,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        # In JSON mode we only report; deletion requires the interactive text flow.
        return 0

    print("Not orphaned (managed by a live Tower Forge CE):")
    print_record_table(managed)
    print()
    print("Orphaned (not managed by an existing Tower Forge CE):")
    print_record_table(orphaned)
    print()
    print(
        f"Summary: {len(batch_envs)} Batch CE(s) total, "
        f"{len(managed)} not orphaned, {len(orphaned)} orphaned."
    )

    if not args.delete:
        return 0

    # ---- Deletion path ----
    if not orphaned:
        print("\nNothing to delete.")
        return 0

    if args.dry_run:
        print(f"\nDry run: would delete {len(orphaned)} orphaned CE(s):")
        for record in orphaned:
            print(f"  - {record['name']}")
        return 0

    print(
        f"\nWARNING: this will DISABLE and DELETE {len(orphaned)} orphaned compute "
        "environment(s) and their associated job queues. This is not reversible."
    )
    if not args.yes:
        confirm = input("Type 'yes' to proceed: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return 0

    print()
    deleted = 0
    failed = 0
    for index, record in enumerate(orphaned, start=1):
        print(f"[{index}/{len(orphaned)}] Deleting: {record['name']}")
        if delete_orphan(batch, record, verbose=True):
            print("  + delete initiated")
            deleted += 1
        else:
            failed += 1

    print()
    print("Deletion Summary")
    print("================")
    print(f"Orphaned processed:   {len(orphaned)}")
    print(f"Successfully deleted: {deleted}")
    print(f"Failed:               {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
