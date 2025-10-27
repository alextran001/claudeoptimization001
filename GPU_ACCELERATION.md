## GPU Acceleration Guide

## ⚠️ IMPORTANT: Profile First!

**Before enabling GPU acceleration**, we need to identify the **actual bottleneck**:

### Step 1: Profile Your Current Setup

Run this on your beamline system:

```bash
python profile_validation.py path/to/your/excel/file.xlsx
```

This will show you WHERE the time is spent:

```
Possible Bottlenecks:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Excel I/O        - Reading/writing Excel files
2. Qt GUI updates   - processEvents(), signal emissions
3. Pandas operations - Data validation and transformation
4. Redis operations  - Database writes
5. Type conversions  - astype() calls
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**GPU Only Helps with #3 (Pandas operations)**

If your bottleneck is #1, #2, #4, or #5, GPU won't help!

---

## Why No Improvement from Vectorization?

If the vectorization optimizations showed **no improvement**, likely causes:

### 1. **Bottleneck is Qt GUI Updates**
```python
# These are slow and can't be GPU-accelerated:
QtWidgets.QApplication.processEvents()  # ~10-50ms per call
self.dataChanged.emit()                 # Qt signal overhead
self._changeCellColors()                # GUI repainting
```

**Solution:**
- Reduce processEvents frequency (already done)
- Batch signal emissions (already done)
- Use headless mode for bulk validation

### 2. **Bottleneck is Excel I/O**
```python
# Reading Excel is slow:
df = pd.read_excel(file)  # 1-5 seconds for large files

# Writing Excel is slow:
df.to_excel('output.xlsx')  # 1-3 seconds
```

**Solution:**
- Use CSV instead of Excel (10x faster)
- Disable debug Excel saving (already done)
- Use xlrd/openpyxl with optimizations

### 3. **Bottleneck is Redis Operations**
```python
# Even with batching, Redis can be slow:
self.client.set()    # Network latency
self.client.hset()   # Multiple operations
```

**Solution:**
- Ensure Redis is on localhost (not network)
- Use larger pipeline batches
- Enable Redis persistence optimizations

### 4. **Dataset is Too Small**
```python
# Optimization overhead > computation time
# If dataset < 100 rows, optimizations don't help
```

**Solution:**
- Accept current performance
- Focus on other bottlenecks

---

## GPU Acceleration Setup

**ONLY proceed with GPU if:**
- ✅ Profiler shows pandas operations are the bottleneck
- ✅ Dataset has 1,000+ rows
- ✅ You have NVIDIA GPU (compute capability 6.0+)
- ✅ Pandas operations take > 10 seconds

### Requirements

1. **Hardware:**
   - NVIDIA GPU (GTX 1060 or better)
   - 4+ GB GPU memory
   - CUDA 11.2+ compatible GPU

2. **Software:**
   - CUDA Toolkit 11.2, 11.4, 11.5, or 11.8
   - Python 3.8, 3.9, or 3.10
   - conda package manager

### Installation

#### Option 1: New Conda Environment (Recommended)

```bash
# Create new environment with GPU support
conda create -n nyx-gpu python=3.10 -y
conda activate nyx-gpu

# Install RAPIDS (includes cuDF)
conda install -c rapidsai -c conda-forge -c nvidia \
    cudf=23.12 python=3.10 cuda-version=11.8

# Install PyQt5 and other dependencies
conda install -c conda-forge pyqt pandas redis-py pyyaml openpyxl xlrd

# Verify installation
python -c "import cudf; print('✓ cuDF installed')"
```

#### Option 2: Add to Existing Environment

```bash
# Activate your existing environment
conda activate your-env-name

# Install RAPIDS
conda install -c rapidsai -c conda-forge -c nvidia \
    cudf=23.12 cuda-version=11.8

# Verify
python utils/gpu_validation.py
```

### Check GPU Setup

```bash
python utils/gpu_validation.py
```

Expected output:
```
======================================================================
GPU ACCELERATION SETUP CHECK
======================================================================
✓ cuDF installed
✓ cuDF working correctly
✓ cuPy installed
✓ CUDA version: 11080
✓ GPU: NVIDIA GeForce RTX 3070
✓ GPU Memory: 6.85 GB free
======================================================================
```

---

## Usage

### Option 1: Enable GPU in Code

Edit `utils/pandas_model.py`:

```python
# Add at top of file
from utils.gpu_validation import GPUValidator, GPU_AVAILABLE

class PuckPandasModel(BasePandasModel):
    def __init__(self, *args, use_gpu=False, **kwargs):
        super().__init__(*args, **kwargs)
        # ...

        # Enable GPU
        self.use_gpu = use_gpu and GPU_AVAILABLE
        self.gpu_validator = GPUValidator() if self.use_gpu else None
```

### Option 2: Auto-Enable for Large Datasets

```python
# In import_pucks.py, importExcel():
use_gpu = len(data) > 1000 and GPU_AVAILABLE
self.model = PuckPandasModel(data, use_gpu=use_gpu)
print(f"Using {'GPU' if use_gpu else 'CPU'} for validation")
```

### Option 3: Configuration File

```yaml
# config.yaml
use_gpu_acceleration: true  # Enable GPU if available
gpu_threshold_rows: 1000    # Min rows to use GPU
```

---

## Benchmarking

Test GPU vs CPU on your actual data:

```bash
cd /path/to/nyximportermasterdir
python -c "
from utils.gpu_validation import GPUValidator
import pandas as pd

# Load your data
df = pd.read_excel('data/PSL-20250524.xlsx')

# Benchmark
validator = GPUValidator()
validator.benchmark_gpu_vs_cpu(df, num_runs=3)
"
```

Example output:
```
======================================================================
GPU vs CPU Benchmark (10000 rows)
======================================================================

⏱️  CPU Validation...
   Run 1: 2.341s
   Run 2: 2.298s
   Run 3: 2.315s

⏱️  GPU Validation...
   Run 1: 0.423s
   Run 2: 0.387s
   Run 3: 0.401s

======================================================================
RESULTS
======================================================================
CPU Average: 2.318s
GPU Average: 0.404s
✅ GPU is 5.7x FASTER

💡 Recommendation:
   GPU provides significant speedup - USE GPU
======================================================================
```

---

## Performance Expectations

### GPU Speedup by Dataset Size

```
Rows     | CPU Time | GPU Time | Speedup | Recommendation
---------|----------|----------|---------|------------------
100      | 0.5s     | 0.8s     | 0.6x    | ❌ Too small
1,000    | 2.5s     | 1.2s     | 2.1x    | ⚠️  Marginal
5,000    | 12s      | 2.5s     | 4.8x    | ✅ Good
10,000   | 25s      | 4.5s     | 5.6x    | ✅ Excellent
50,000   | 125s     | 15s      | 8.3x    | ✅ Amazing
```

**Note:** GPU has ~500ms overhead for data transfer. Only worth it for datasets > 1000 rows.

---

## Troubleshooting

### GPU Not Detected

```bash
# Check NVIDIA drivers
nvidia-smi

# Check CUDA
nvcc --version

# Reinstall cuDF with specific CUDA version
conda install -c rapidsai -c conda-forge cudf cuda-version=11.8
```

### "CUDA error: out of memory"

GPU ran out of memory. Solutions:

```python
# 1. Process in smaller chunks
chunk_size = 5000
for i in range(0, len(df), chunk_size):
    chunk = df[i:i+chunk_size]
    # Process chunk

# 2. Clear GPU memory
import cupy as cp
mempool = cp.get_default_memory_pool()
mempool.free_all_blocks()

# 3. Use smaller batch size
```

### "cuDF import error"

```bash
# Ensure CUDA version matches
python -c "import torch; print(torch.version.cuda)"  # Check PyTorch CUDA
conda list | grep cuda  # Check installed CUDA

# Reinstall matching version
conda install cudf cuda-version=11.8
```

### Still No Speedup

If GPU shows no improvement:

1. **Bottleneck is elsewhere** (GUI/I/O)
   → Profile with `profile_validation.py`

2. **Dataset too small** (< 1000 rows)
   → GPU overhead > gains

3. **GPU too slow** (old GPU)
   → Need GTX 1060 or better

4. **Data transfer overhead**
   → Process more operations on GPU before transferring back

---

## Alternative Solutions (If GPU Doesn't Help)

### 1. Disable GUI During Validation

```python
# Run validation in headless mode
def validate_headless(df):
    model = PuckPandasModel(df)
    model.progress_callback = None  # No GUI updates
    model.preprocessData()
    model.validateData(config)
    return model
```

### 2. Use Faster Excel Library

```python
# Replace openpyxl with faster alternatives
import pyxlsb  # For .xlsb files (10x faster)
import fastexcel  # Rust-based Excel reader

df = fastexcel.read_excel('file.xlsx')  # Much faster
```

### 3. Cache Validation Results

```python
# Cache validation between runs
import hashlib
import pickle

def get_file_hash(filepath):
    with open(filepath, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()

file_hash = get_file_hash(excel_path)
cache_file = f"cache_{file_hash}.pkl"

if os.path.exists(cache_file):
    # Load cached validation
    model = pickle.load(open(cache_file, 'rb'))
else:
    # Validate and cache
    model = validate(df)
    pickle.dump(model, open(cache_file, 'wb'))
```

### 4. Optimize Qt GUI

```python
# Reduce GUI updates
model.blockSignals(True)  # Disable signals during bulk operations
# ... do validation ...
model.blockSignals(False)  # Re-enable
model.layoutChanged.emit()  # Single update at end
```

### 5. Use Numba JIT Compilation

```python
from numba import jit

@jit(nopython=True)
def validate_samples_numba(samples):
    # Compiled to machine code (50-100x faster)
    valid = np.zeros(len(samples), dtype=np.bool_)
    for i in range(len(samples)):
        # Validation logic
        valid[i] = check_sample(samples[i])
    return valid
```

---

## Summary

**Recommended Debugging Steps:**

1. ✅ **Profile first** with `profile_validation.py`
2. ✅ Identify actual bottleneck (GPU only helps with pandas operations)
3. ✅ If pandas is bottleneck AND dataset > 1000 rows → Try GPU
4. ✅ If GUI/I/O is bottleneck → Optimize those instead
5. ✅ If dataset < 1000 rows → Accept current performance

**Quick Decision Tree:**

```
Is validation taking > 30 seconds?
  └─ YES: Run profiler to find bottleneck
       ├─ Pandas operations slow? → Try GPU
       ├─ Qt GUI slow? → Reduce GUI updates
       ├─ Excel I/O slow? → Use faster library
       └─ Redis slow? → Optimize Redis config
  └─ NO: Current performance acceptable
```

Let me know what the profiler shows, and I can help optimize the actual bottleneck! 🚀
