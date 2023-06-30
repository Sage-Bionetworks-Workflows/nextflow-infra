cd $RAFT_PATH/references

# mhcflurry data directory
mkdir -p mhcflurry
cd mhcflurry
mkdir -p tmp
cd tmp
wget https://github.com/openvax/mhcflurry/releases/download/pre-2.0/models_class1_presentation.20200611.tar.bz2
tar xvf *
mv models/* ../
cd ..
rm -rf tmp
cd ..

# Viral reference
mkdir -p viral; cd viral
wget https://github.com/dmarron/virdetect/raw/master/reference/virus_masked_hg38.fa
wget https://gitlab.com/landscape-of-effective-neoantigens-software/nextflow/modules/tools/lens/-/wikis/uploads/4dedb99984857905ee96ab1d148d7863/virdetect.cds.gff.gz
wget https://gitlab.com/landscape-of-effective-neoantigens-software/nextflow/modules/tools/lens/-/wikis/uploads/ad52c657d06c12d7a3346f15b71390af/virus.cds.fa.gz
wget https://gitlab.com/landscape-of-effective-neoantigens-software/nextflow/modules/tools/lens/-/wikis/uploads/9e3a49921bd325caa98dcd9211f8cdd9/virus.pep.fa.gz
gunzip *
cd ..

# antigen.garnish data directory
# The gzip extracts to the desired directory, so no mkdir and cd required.
curl -fsSL "https://s3.amazonaws.com/get.rech.io/antigen.garnish-2.3.0.tar.gz" | tar -xvz
chmod -R 700 antigen.garnish

# BLASTP binary (for antigen.garnish)
mkdir -p bin; cd bin
wget https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.13.0/ncbi-blast-2.13.0+-x64-linux.tar.gz
tar xvf *gz
mv ncbi*/bin/blastp .
rm -rf ncbi*
mv blastp ../antigen.garnish
cd ..
rm -rf bin

# Make dummy_file
touch dummy_file
