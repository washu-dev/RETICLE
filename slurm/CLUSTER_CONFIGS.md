# SLURM Cluster Configuration Templates

Copy these configurations and customize for your specific HPC cluster.

## Common Cluster Types

### Type 1: Small University Cluster (< 128 cores, < 512GB RAM)

**Characteristics:**
- Shared resources
- Limited GPU availability
- CPU partition: cpu, gpu

**Configuration:**

```bash
# env-setup.sh
# Load any required modules (example - adjust for your cluster)
# module load python/3.11
# module load gcc/11

# reticle-etl.sh
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:00:00        # Longer timeout due to contention
#SBATCH --partition=cpu
```

**Commands:**
```bash
# CPU job
./submit-etl-job.sh 2 --cores 8 --mem 32

# GPU job (if available)
./submit-etl-job.sh 2 --gpu --gpus 1 --time 00:30:00
```

---

### Type 2: Medium Research Cluster (128-512 cores, 1-4TB RAM, 2-8 GPUs)

**Characteristics:**
- Moderate resource availability
- Multiple GPU types
- Partitions: cpu, gpu, gpu-high-mem

**Configuration:**

```bash
# env-setup.sh
# Example for XSEDE/ACCESS cluster
module load anaconda3/2023.09
module load gcc/12.1.0

# reticle-etl.sh
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=00:30:00
#SBATCH --partition=cpu

# env-setup-gpu.sh
module load cuda/12.0
module load cudnn/8.6
```

**Commands:**
```bash
# CPU: multi-core processing
./submit-etl-job.sh 2 --cores 32 --mem 128

# GPU: 1-2 GPUs typical
./submit-etl-job.sh 2 --gpu --gpus 1

# Large dataset: multi-GPU
./submit-etl-job.sh 3 --gpu --gpus 2 --time 01:00:00
```

---

### Type 3: Large HPC Center (512+ cores, 4TB+ RAM, 8+ GPUs)

**Characteristics:**
- Abundant resources
- Latest GPU hardware
- Multiple specialized partitions
- Advanced scheduler features

**Configuration:**

```bash
# env-setup.sh
module load compiler/gcc/11.2.0
module load python/3.11
module load hpe-mpi/2.18

# reticle-etl.sh
#SBATCH --cpus-per-task=32
#SBATCH --mem=128G
#SBATCH --time=00:20:00
#SBATCH --partition=compute

# env-setup-gpu.sh
module load cuda/12.2
module load cudnn/8.6
module load nccl/2.18
```

**Commands:**
```bash
# CPU: use all available cores
./submit-etl-job.sh 2 --cores 64 --mem 256

# GPU: single GPU optimal for this workload
./submit-etl-job.sh 2 --gpu --gpus 1

# Multi-GPU for large datasets
./submit-etl-job.sh 3 --gpu --gpus 4 --time 00:45:00
```

---

## Cloud HPC (AWS/Azure/GCP)

### AWS EC2 with SLURM

**Instance Types:**
- CPU: c5.9xlarge (32 cores, 72GB) or larger
- GPU: p3.2xlarge (1x V100) or p3.8xlarge (4x V100)

**Configuration:**

```bash
# env-setup.sh
# AWS ParallelCluster provides python
module load intelmpi
module load aws-parallelcluster

# reticle-etl.sh
#SBATCH --cpus-per-task=32
#SBATCH --mem=72G
#SBATCH --time=00:20:00
#SBATCH --partition=compute
```

### Azure CycleCloud with SLURM

**Configuration:**

```bash
# env-setup.sh
module load intel-mkl
module load cuda/11.8

# reticle-etl.sh similar to AWS
```

---

## Cluster-Specific Guides

### XSEDE/ACCESS (NSF)

Common clusters: Stampede3, Frontera, Bridges3

```bash
# env-setup.sh
module load python/3.11
module load gcc/11.2.0
module load intel-mkl

# Submit to appropriate partition
./submit-etl-job.sh 2 --cores 32 --partition compute --mem 128
./submit-etl-job.sh 2 --gpu --gpus 1 --partition gpu
```

### NERSC (Lawrence Berkeley Lab)

Common cluster: Perlmutter

```bash
# env-setup.sh
module load python
module load gcc

# GPU configuration
module load cudatoolkit/12.0
module load nccl

# Note: Perlmutter has specific GPU partitions
./submit-etl-job.sh 2 --gpu --gpus 1 --partition gpu
```

### TACC (University of Texas)

Common cluster: Stampede3

```bash
# env-setup.sh
module use /opt/apps/intel19/modulefiles
module load intel/19.1.1
module load impi/19.0.9
module load python3/3.10-2022-03

# GPU: Stampede3 has GPU partition
./submit-etl-job.sh 2 --gpu --gpus 2 --partition gpu
```

---

## Custom Configuration Checklist

When adapting for your cluster:

1. **Module System**
   - [ ] Does your cluster use modules? (`module avail` to check)
   - [ ] What Python version is available? (`module avail python`)
   - [ ] What compiler is available? (`module avail gcc`)
   - [ ] Is CUDA available? (`module avail cuda`)

2. **Environment Setup**
   - [ ] Add required modules to `env-setup.sh`
   - [ ] For GPU, add CUDA/cuDNN to `env-setup-gpu.sh`
   - [ ] Test with: `bash env-setup.sh`

3. **Partitions**
   - [ ] What partitions exist? (`sinfo`)
   - [ ] What are time limits? (`sinfo -l`)
   - [ ] What resource limits apply? (`scontrol show partition <name>`)

4. **Resource Constraints**
   - [ ] Max CPUs per job?
   - [ ] Max memory per job?
   - [ ] Max GPUs per node?
   - [ ] Typical node configuration?

5. **Conda/Python**
   - [ ] Does your cluster have conda pre-installed?
   - [ ] Can you create new environments?
   - [ ] Is GPU acceleration available (RAPIDS)?

---

## Testing Your Configuration

After customizing for your cluster:

```bash
# 1. Test basic job submission
./submit-etl-job.sh 1 --cores 4 --mem 16 --time 00:10:00

# 2. Monitor
./monitor-etl-jobs.sh

# 3. Check logs
./monitor-etl-jobs.sh <job_id> log

# 4. Verify performance
./monitor-etl-jobs.sh <job_id> log | grep "Loaded"
```

---

## Troubleshooting by Cluster Type

### Small Cluster: Job Queues for Hours
```bash
# Reduce resource request
./submit-etl-job.sh 2 --cores 4 --mem 16

# Or use --partition for faster queue
./submit-etl-job.sh 2 --partition fast  # if available
```

### GPU Cluster: CUDA Not Found
```bash
# Check CUDA module
module avail cuda

# Update env-setup-gpu.sh with correct module name
# Then re-submit
./submit-etl-job.sh 2 --gpu
```

### Large Cluster: Job Killed for Exceeding Limits
```bash
# Check partition limits
scontrol show partition <name>

# Adjust time or memory
./submit-etl-job.sh 2 --mem 512 --time 00:15:00
```

---

## Support

If your cluster is not listed:
1. Contact your cluster support team for module names
2. Ask them for example SLURM scripts
3. Adapt the templates above
4. Test with small job first (`--cores 4 --mem 16 --time 00:10:00`)
