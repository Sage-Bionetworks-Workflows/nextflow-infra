cd $1/references
mkdir -p mus_musculus; cd mus_musculus

# Genomic reference
mkdir -p fasta; cd fasta
wget https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_mouse/release_M25/GRCm38.primary_assembly.genome.fa.gz
gunzip GRCm38.primary_assembly.genome.fa.gz
cd ..

# GTF/GFF3
mkdir -p annot; cd annot
wget ftp://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_mouse/release_M25/gencode.vM25.annotation.gtf.gz
wget http://geve.med.u-tokai.ac.jp/download_data/gtf_m/Mmus38.geve.m_v1.gtf.bz2
bzip2 -d Mmus38.geve.m_v1.gtf.bz2
zcat gencode.vM25.annotation.gtf.gz | grep -v chrMG > gencode.vM25.annotation.with.mervs.gtf
cat Mmus38.geve.m_v1.gtf | sed 's/^/chr/g' | sed 's/CDS/transcript/g' >> gencode.vM25.annotation.with.mervs.gtf
cat Mmus38.geve.m_v1.gtf | sed 's/^/chr/g' | sed 's/CDS/exon/g' >> gencode.vM25.annotation.with.mervs.gtf
wget ftp://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_mouse/release_M25/gencode.vM25.annotation.gff3.gz
gunzip gencode.vM25.annotation.gff3.gz
cd ..

# Protein reference
mkdir -p fasta; cd fasta
wget ftp://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_mouse/release_M25/gencode.vM25.pc_translations.fa.gz
gunzip gencode.vM25.pc_translations.fa.gz
cd ..

# Reference VCFs
mkdir -p vcfs; cd vcfs
# From https://github.com/igordot/genomics/blob/master/workflows/gatk-mouse-mm10.md
wget --recursive --no-parent --no-directories \
--accept vcf*vcf.gz \
ftp://ftp.ncbi.nih.gov/snp/organisms/archive/mouse_10090/VCF/
rm *Alt*
rm *MT*
rm *Multi*
rm *NotOn*
rm *Un*
for vcf in $(ls -1 vcf_chr_*.vcf.gz) ; do
  vcf_new=${vcf/.vcf.gz/.vcf}
  echo $vcf
  zcat $vcf | sed 's/^\([0-9XY]\)/chr\1/' > $vcf_new
  rm -fv $vcf
done
for i in *vcf; do echo ${i}; bgzip ${i}; done
for i in *vcf.gz; do echo ${i}; tabix ${i}; done
bcftools merge -Oz -o mm10.dbsnp.vcf.gz *vcf.gz
rm vcf*
cd ..

# BEDs
# https://www.biostars.org/p/459269/#459274
mkdir -p beds; cd beds
zgrep 'transcript_type "protein_coding"' ../annot/gencode.vM25.annotation.gtf.gz | awk '($3=="exon") {printf("%s\t%s\t%s\n",$1,int($4)-1,$5);}' | sort -T . -t $'\t' -k1,1 -k2,2n | bedtools merge > mm10_exome.bed
cd ..

# snpEff reference
mkdir -p snpeff; cd snpeff
singularity pull docker://resolwebio/snpeff:latest
singularity exec -B $PWD snpeff_latest.sif /opt/snpeff/snpeff/bin/snpEff download GRCm38.86 -dataDir ${PWD}
rm snpeff_latest.sif
wget https://gitlab.com/landscape-of-effective-neoantigens-software/nextflow/modules/tools/lens/-/wikis/uploads/430f9d80c841721499fbcec937b0f721/snpEff.config
cd ..

# NeoSplice reference
mkdir -p neosplice; cd neosplice
wget https://raw.githubusercontent.com/max555beyond/NeoSplice/master/generate_reference_peptidome.py
python generate_reference_peptidome.py ../annot/gencode.vM25.annotation.gff3 ../fasta/GRCm38.primary_assembly.genome.fa .
mv .peptidome_result/ peptidome.mus_musculus
rm generate_reference_peptidome.py
cd ..

# CTA/Self-antigen reference
mkdir -p cta_self; cd cta_self
wget https://gitlab.com/landscape-of-effective-neoantigens-software/nextflow/modules/tools/lens/-/wikis/uploads/7f7454717866c1a61fb505f8ac5446e0/cta_and_self_antigen.mus_musculus.gene_list
cd ..

# STARFusion reference
mkdir -p starfusion; cd starfusion
wget https://data.broadinstitute.org/Trinity/CTAT_RESOURCE_LIB/__genome_libs_StarFv1.9/Mouse_gencode_M24_CTAT_lib_Apr062020.plug-n-play.tar.gz
tar -xvf Mouse_gencode_M24_CTAT_lib_Apr062020.plug-n-play.tar.gz
cd Mouse_gencode_M24_CTAT_lib_Apr062020.plug-n-play
mv ctat_genome_lib_build_dir/* .; rm -rf ctat_genome_lib_build_dir/; cd ..
rm -rf Mouse_gencode_M24_CTAT_lib_Apr062020.plug-n-play.tar.gz
cd ..

# ERV reference
mkdir -p erv; cd erv
wget http://geve.med.u-tokai.ac.jp/download_data/table/Mmus38.txt.bz2
bzip2 -d Mmus38.txt.bz2
cd ..
