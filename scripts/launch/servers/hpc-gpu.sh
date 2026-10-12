# Example settings for GPU jobs on a Slurm cluster. Replace the values with your cluster's.
# This file becomes the top of the job script: #SBATCH lines first, then setup commands.
# Override single flags per launch: slurm.sh --sbatch "--time=12:00:00 --gres=gpu:2" ...

#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=04:00:00

# Setup commands, run on the compute node before the job starts.
# module load Python/3.11 CUDA/12.4
