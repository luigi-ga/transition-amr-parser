set -o errexit
set -o nounset
set -o pipefail 

# load local variables used below
. scripts/local_variables.sh

[ ! -d ${oracle_folder}/ ] && mkdir ${oracle_folder}/

# Use the standalone parser
amr-parse \
    --in-sentences ${oracle_folder}/dev.tokens \
    --in-model $trained_model \
    --out-amr ${oracle_folder}/dev.amr \
    --batch-size 12 \
    --num-cores 6 \
    --use-gpu \

# evaluate model performance
echo "Evaluating Model"
test_result="$(python smatch/smatch.py --significant 3 -f $dev_file ${oracle_folder}/dev.amr -r 10)"
echo $test_result
