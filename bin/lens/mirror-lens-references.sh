#!/bin/bash

# Refer to the Running LENS instructions and set up your environment accordingly before executing this script:
# https://gitlab.com/landscape-of-effective-neoantigens-software/nextflow/modules/tools/lens/-/wikis/Running-LENS#populate-raft-global-references-directory

# This script assumes that `AWS_PROFILE` has been set to a AWS CLI
# profile that has write-access to the `s3://sage-igenomes` bucket
# (or using any other means of authenticating with the AWS CLI).

# Downloading the LENS reference files will temporarily take up ~72.1 GB of disk space.

prefixes=(
    "antigen.garnish/"
    # "erv/"
    "homo_sapiens/"
    # "mus_musculus/"
    "viral/"
)

echo "Downloading LENS reference files"
mkdir -p "./lens/references"
cd ./lens
bash download_general_references.sh
bash download_human_references.sh
# bash download_mouse_references.sh

for prefix in ${prefixes[*]}; do
    echo "Syncing $prefix..."
    aws s3 --region us-east-1 sync "./references/$prefix/" "s3://sage-igenomes/LENS/$prefix/" --acl public-read
done
cd ..
rm -r "./lens"
