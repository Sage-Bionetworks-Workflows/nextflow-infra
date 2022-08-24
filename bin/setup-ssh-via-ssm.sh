#!/bin/bash

#
# This script uploads your public SSH key ('id_ed25519' by default)
# to a home directory ('ec2-user' by default) on an EC2 instance.
# Written by Bruno Grande.
#
# Usage:    bash setup-ssh-via-ssm.sh INSTANCE_ID
#
# Example:  bash setup-ssh-via-ssm.sh i-0d3ff331a7b7a7e8b
#
#
# This script assumes that:
#
# - You have generated an ed25519 SSH key pair as per
#   GitHub's best practices. Otherwise, you'll need to
#   generate one using:
#
#     ssh-keygen -t ed25519 -C "your_email@example.com"
#
# - Your shell environment is configured with AWS credentials
#   (AWS_PROFILE or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY).
#   For example, if you have an AWS CLI profile based on the
#   Service Catalog docs, you will first need to run this:
#
#     export AWS_PROFILE=service-catalog
#
#   Tip: If you only use the AWS CLI for the Service Catalog,
#   consider making the config profile the default as follows:
#
#     [default]
#     region=us-east-1
#     credential_process = ...
#
# - Your SSH configuration file includes the following snippet
#   (update the value for 'IdentityFile' as appropriate):
#
#     Host i-* mi-*
#         ProxyCommand sh -c "aws ssm start-session --target %h --document-name AWS-StartSSHSession --parameters 'portNumber=%p'"
#         IdentityFile ~/.ssh/id_ed25519
#         User ec2-user
#

# Command-line arguments and optional environment variables
INSTANCE_ID="${1}"
SSH_KEY_PUB="${SSH_KEY_PUB:-$HOME/.ssh/id_ed25519.pub}"
TARGET_USER="${TARGET_USER:-ec2-user}"

# Assemble commands for setting up SSH keys for $TARGET_USER
COMMANDS=$(cat <<- END
  cd
  mkdir -p .ssh;
  echo $(<$SSH_KEY_PUB) > .ssh/authorized_keys;
  chmod 700 .ssh;
  chmod 600 .ssh/authorized_keys;
  sudo rsync -a --chown=${TARGET_USER}:${TARGET_USER} .ssh/ /home/${TARGET_USER}/.ssh/;
END
)

# Run commands remotely on $INSTANCE_ID using SSM
echo
echo "Running the following shell script on ${INSTANCE_ID}..."
echo "$COMMANDS"
aws ssm start-session --target "$INSTANCE_ID" \
        --document-name AWS-StartInteractiveCommand \
        --parameters command="$COMMANDS"

# Attempt to SSH into the instance
echo
echo "You should now be able to connect using 'ssh $INSTANCE_ID'."
echo "You can just use the SSH command for this instance going forward."
echo "Connecting now..."
echo
ssh $INSTANCE_ID
