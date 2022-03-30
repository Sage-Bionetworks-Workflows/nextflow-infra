#!/bin/bash

DATE=$(date +%Y-%m-%d-%H-%M)

SNAPSHOT_ID="snapshot-${USER:-unknown}-$DATE"

aws --no-cli-pager rds create-db-cluster-snapshot --db-cluster-identifier "tower" --db-cluster-snapshot-identifier "$SNAPSHOT_ID" \
&& \
aws rds wait db-cluster-snapshot-available --db-cluster-identifier "tower" --db-cluster-snapshot-identifier "$SNAPSHOT_ID"
