# Nextflow Infrastructure

The AWS infrastructure for hosting a private instance (see link below) of [Nextflow Tower](https://tower.nf/) and executing [Nextflow workflows](https://nextflow.io/) is defined in this repository and deployed using [CloudFormation](https://aws.amazon.com/cloudformation/) via [Sceptre](https://sceptre.cloudreach.com/).

The Nextflow infrastructure has been vetted by Sage IT to process sensitive or controlled-access (_e.g._ PHI) data. Notably, only [HIPAA eligible AWS services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/) are deployed.

## Getting Started

Instructions on how to get started with Tower are described on the [Getting Started with Nextflow and Tower](https://sagebionetworks.jira.com/wiki/spaces/WF/pages/2191556616/Getting+Started+with+Nextflow+and+Tower#Creating-a-Tower-project) wiki page. This page is only accessible to Sage employees.

### Getting Help

Instructions on how to get help are described on the [Getting Started with Nextflow and Tower](https://sagebionetworks.jira.com/wiki/spaces/WF/pages/2191556616/Getting+Started+with+Nextflow+and+Tower#Getting-Help) wiki page. This page is only accessible to Sage employees.

If you are not a Sage employee, you can open an issue on this repository.

### Contributing

Read through the [contribution guidelines](CONTRIBUTING.md) for more information. Contributions are welcome from anyone!

## License

This repository is licensed under the [Apache License 2.0](LICENSE).

Copyright 2022 Sage Bionetworks
