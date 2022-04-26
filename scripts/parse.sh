#!/bin/bash
set -o pipefail 
set -o errexit 
# load local variables used below
. set_environment.sh
HELP="$0 <checkpoint> <tokenized sentences file> <out amr>"
[ "$#" -lt 3 ] && echo "$HELP" && exit 1
checkpoint=$1
input_file=$2
output_amr=$3
srctag=$4
set -o nounset

amr-parse \
    --in-checkpoint $checkpoint \
    --in-tokenized-sentences $input_file \
    --out-amr $output_amr \
    --srctag $srctag \
    --batch-size 64 \
    --roberta-batch-size 1
