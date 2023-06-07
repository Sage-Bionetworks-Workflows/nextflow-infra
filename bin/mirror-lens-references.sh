#!/bin/bash

# This script assumes that `AWS_PROFILE` has been set to a AWS CLI
# profile that has write-access to the `s3://sage-igenomes` bucket
# (or using any other means of authenticating with the AWS CLI).

prefixes=(
    "antigen.garnish/"
    "erv/"
    "homo_sapiens/"
    "mhcflurry/"
    "mus_musculus/"
    "viral/"
)

echo "Downloading LENS reference files"
mkdir -p "./lens/references"
wget -P ./lens https://gitlab.com/landscape-of-effective-neoantigens-software/nextflow/modules/tools/lens/-/wikis/uploads/b0d8a24036628bd9e6c860eb531919c3/download_general_references.sh \
    https://gitlab.com/landscape-of-effective-neoantigens-software/nextflow/modules/tools/lens/-/wikis/uploads/2238c7f4af5c5499f298315bf5080ad7/download_human_references.sh \
    https://gitlab.com/landscape-of-effective-neoantigens-software/nextflow/modules/tools/lens/-/wikis/uploads/bf210753e3724edf6db2543eb54c3de4/download_mouse_references.sh
bash download_general_references.sh ./references
bash download_human_references.sh ./references
bash download_mouse_references.sh ./references

for prefix in ${prefixes[*]}; do
    echo "Syncing $prefix..."
    aws s3 --region us-east-1 sync "./references/$prefix/" "s3://sage-igenomes/LENS/$prefix/" --acl public-read
done

rm -r "./lens"
