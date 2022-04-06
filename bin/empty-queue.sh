#!/bin/bash

JOB_QUEUE="${1}"
NUM_CPUS="${2:-4}"

for state in SUBMITTED PENDING RUNNABLE STARTING RUNNING
do
    aws batch list-jobs --job-queue "$JOB_QUEUE" --job-status "$state" --output 'text' --query 'jobSummaryList[*].[jobId]' \
        | parallel --eta --jobs "$NUM_CPUS" 'aws batch terminate-job --reason "Terminating job." --job-id {}'
done
