#!/bin/bash

# This script assumes that `AWS_PROFILE` has been set to a AWS CLI
# profile that has write-access to the `s3://sage-igenomes` bucket
# (or using any other means of authenticating with the AWS CLI).

prefixes=(
    "Homo_sapiens/Ensembl/GRCh37"
    "Homo_sapiens/NCBI/GRCh38"
    "Mus_musculus/Ensembl/GRCm38"
    "Homo_sapiens/UCSC/hg38"
    "Homo_sapiens/UCSC/hg19"
    "Mus_musculus/UCSC/mm10"
    "Homo_sapiens/GATK/GRCh37"
    "Homo_sapiens/GATK/GRCh38"
)

for prefix in ${prefixes[*]}; do
    echo "Syncing $prefix..."
    mkdir -p "./$prefix/" \
    && aws s3 --no-sign-request --region eu-west-1 sync "s3://ngi-igenomes/igenomes/$prefix/" "./$prefix/" \
    && aws s3 --region us-east-1 sync "./$prefix/" "s3://sage-igenomes/igenomes/$prefix/" \
    && rm -r "./$prefix/"
done
