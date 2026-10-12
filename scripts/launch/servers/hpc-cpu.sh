# Example settings for CPU jobs on a Slurm cluster. Replace the values with your cluster's.
# This file becomes the top of the job script: #SBATCH lines first, then setup commands.

#SBATCH --partition=cpu
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=02:00:00

# Setup commands, run on the compute node before the job starts.
# module load Python/3.11
