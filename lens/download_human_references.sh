export RAFT_PATH=~/raft
export REFERENCES_PATH=$RAFT_PATH/references
cd $REFERENCES_PATH

# set up homo sapiens directory
mkdir -p homo_sapiens; cd homo_sapiens
export HUMAN_REFERENCES_PATH=$REFERENCES_PATH/homo_sapiens 

# Genomic reference
mkdir -p fasta; cd fasta
wget https://storage.googleapis.com/genomics-public-data/resources/broad/hg38/v0/Homo_sapiens_assembly38.fasta
docker pull staphb/samtools:1.13
docker run -v $PWD:/data staphb/samtools:1.13 samtools faidx Homo_sapiens_assembly38.fasta
# EBV removal strategy from https://bioinformatics.stackexchange.com/a/14421
keep_ids=($(awk '{print $1}' Homo_sapiens_assembly38.fasta.fai | grep -v chrEBV))
docker run -v $PWD:/data staphb/samtools:1.13 samtools faidx -o Homo_sapiens.assembly38.no_ebv.fa Homo_sapiens_assembly38.fasta "${keep_ids[@]}"
rm -f *.fasta*
cd $HUMAN_REFERENCES_PATH

# stopped here

# GTF/GFF3
mkdir -p annot; cd annot
wget ftp://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_37/gencode.v37.annotation.gtf.gz
wget http://geve.med.u-tokai.ac.jp/download_data/gtf_m/Hsap38.geve.m_v1.gtf.bz2
bzip2 -d Hsap38.geve.m_v1.gtf.bz2
zcat gencode.v37.annotation.gtf.gz > gencode.v37.annotation.with.hervs.gtf
cat Hsap38.geve.m_v1.gtf | sed 's/^/chr/g' | sed 's/CDS/transcript/g' >> gencode.v37.annotation.with.hervs.gtf
cat Hsap38.geve.m_v1.gtf | sed 's/^/chr/g' | sed 's/CDS/exon/g' >> gencode.v37.annotation.with.hervs.gtf
wget ftp://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_37/gencode.v37.annotation.gff3.gz
gunzip gencode.v37.annotation.gff3.gz
cd $HUMAN_REFERENCES_PATH

# Protein reference
mkdir -p protein; cd protein
wget ftp://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_37/gencode.v37.pc_translations.fa.gz
gunzip gencode.v37.pc_translations.fa.gz
cd $HUMAN_REFERENCES_PATH

# Reference VCFs
mkdir -p vcfs; cd vcfs
wget https://storage.googleapis.com/gatk-best-practices/somatic-hg38/1000g_pon.hg38.vcf.gz
wget https://storage.googleapis.com/gatk-best-practices/somatic-hg38/af-only-gnomad.hg38.vcf.gz
wget https://storage.googleapis.com/genomics-public-data/resources/broad/hg38/v0/Homo_sapiens_assembly38.dbsnp138.vcf
wget https://storage.googleapis.com/gatk-best-practices/somatic-hg38/small_exac_common_3.hg38.vcf.gz
bgzip Homo_sapiens_assembly38.dbsnp138.vcf
cd $HUMAN_REFERENCES_PATH


# BEDs
# https://www.biostars.org/p/459269/#459274
mkdir -p beds; cd beds
zgrep 'transcript_type "protein_coding"' $HUMAN_REFERENCES_PATH/annot/gencode.v37.annotation.gtf.gz | awk '($3=="exon") {printf("%s\t%s\t%s\n",$1,int($4)-1,$5);}' | sort -T . -t $'\t' -k1,1 -k2,2n | bedtools merge > hg38_exome.bed
cd $HUMAN_REFERENCES_PATH


# snpEff reference
mkdir -p snpeff; cd snpeff
docker pull resolwebio/snpeff:2.0.0
mkdir -p GRCh38.GENCODEv37; cd GRCh38.GENCODEv37
wget https://gitlab.com/landscape-of-effective-neoantigens-software/nextflow/modules/tools/lens/-/wikis/uploads/430f9d80c841721499fbcec937b0f721/snpEff.config
ln $HUMAN_REFERENCES_PATH/annot/gencode.v37.annotation.gtf.gz genes.gtf.gz
sudo ln $HUMAN_REFERENCES_PATH/fasta/Homo_sapiens.assembly38.no_ebv.fa sequences.fa
cd $HUMAN_REFERENCES_PATH/snpeff
docker run -v $PWD:/data resolwebio/snpeff:2.0.0 /opt/snpeff/snpeff/bin/snpEff build -gtf22 -v GRCh38.GENCODEv37 -dataDir ${PWD} -c GRCh38.GENCODEv37/snpEff.config
rm -f GRCh38.GENCODEv37/sequences.fa GRCh38.GENCODEv37/genes.gtf.gz
cd $HUMAN_REFERENCES_PATH


# NeoSplice reference
mkdir -p neosplice; cd neosplice
### The steps below generates a peptidome specific to a GTF and reference
### FASTA which is ideal. The Python script is taxing though, and users may not
### be able to run the script. As an alternative, the "off-the-shelf" peptidome
### included with NeoSplice is provided by default.

# wget https://raw.githubusercontent.com/max555beyond/NeoSplice/master/generate_reference_peptidome.py
# python3 -m pip install --user pyfaidx
# python3 -m pip install --user bcbio-gff
# sed 's/os.makedirs(path, 0777)/os.makedirs(path, 0777)/g' generate_reference_peptidome.py > generate_reference_peptidome.py.tmp
# mv generate_reference_peptidome.py.tmp generate_reference_peptidome.py
# python3 generate_reference_peptidome.py $HUMAN_REFERENCES_PATH/annot/gencode.v37.annotation.gff3 $HUMAN_REFERENCES_PATH/fasta/Homo_sapiens.assembly38.no_ebv.fa .
# mv .peptidome_result/ peptidome.homo_sapiens
# rm generate_reference_peptidome.py

mkdir -p peptidome.homo_sapiens; cd peptidome.homo_sapiens

wget https://github.com/Benjamin-Vincent-Lab/NeoSplice/blob/master/Reference_peptidome/reference_peptidome_8.txt.gz
wget https://github.com/Benjamin-Vincent-Lab/NeoSplice/blob/master/Reference_peptidome/reference_peptidome_9.txt.gz
wget https://github.com/Benjamin-Vincent-Lab/NeoSplice/blob/master/Reference_peptidome/reference_peptidome_10.txt.gz
wget https://github.com/Benjamin-Vincent-Lab/NeoSplice/blob/master/Reference_peptidome/reference_peptidome_11.txt.gz

cd $HUMAN_REFERENCES_PATH

# CTA/Self-antigen reference
mkdir -p cta_self; cd cta_self
wget https://gitlab.com/landscape-of-effective-neoantigens-software/nextflow/modules/tools/lens/-/wikis/uploads/5a9786203497b90c0cc0c0a6a251399b/cta_and_self_antigen.homo_sapiens.gene_list
cd $HUMAN_REFERENCES_PATH

# STARFusion reference
# Note: This file is quite large (31G), so ensure you have sufficient storage.
mkdir -p starfusion; cd starfusion
wget https://data.broadinstitute.org/Trinity/CTAT_RESOURCE_LIB/__genome_libs_StarFv1.10/GRCh38_gencode_v37_CTAT_lib_Mar012021.plug-n-play.tar.gz
tar -xvf GRCh38_gencode_v37_CTAT_lib_Mar012021.plug-n-play.tar.gz
cd GRCh38_gencode_v37_CTAT_lib_Mar012021.plug-n-play
mv ctat_genome_lib_build_dir/* .; rm -rf ctat_genome_lib_build_dir/; cd ..
rm -rf GRCh38_gencode_v37_CTAT_lib_Mar012021.plug-n-play.tar.gz
cd $HUMAN_REFERENCES_PATH

# ERV reference
mkdir -p erv; cd erv
wget http://geve.med.u-tokai.ac.jp/download_data/table/Hsap38.txt.bz2
bzip2 -d Hsap38.txt.bz2
cd $HUMAN_REFERENCES_PATH

# TCGA external reference
mkdir -p tcga; cd tcga
python3 -m pip install numpy --user
wget https://toil-xena-hub.s3.us-east-1.amazonaws.com/download/tcga_rsem_isoform_tpm.gz
wget https://gitlab.com/landscape-of-effective-neoantigens-software/nextflow/modules/tools/lens/-/wikis/uploads/5e315a7217ff68ee2ced894e8a4a7246/tissue_source_site_codes
wget https://gitlab.com/landscape-of-effective-neoantigens-software/tcga2lens/-/raw/0e4ac67007b5e77b151162465b44003f555951a4/tcga2lens.py
python3 tcga2lens.py summarize-transcript-expression --tx-file tcga_rsem_isoform_tpm.gz --tumor-type-map tissue_source_site_codes --output tcga_transcript_tpm_summary.tsv
cd $HUMAN_REFERENCES_PATH
