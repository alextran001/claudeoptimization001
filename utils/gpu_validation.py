"""
GPU-Accelerated Validation using NVIDIA RAPIDS (cuDF)

REQUIREMENTS:
- NVIDIA GPU (compute capability 6.0+)
- CUDA Toolkit 11.2+
- cuDF library: conda install -c rapidsai -c conda-forge cudf

This can provide 10-100x speedup for large datasets on GPU.
Falls back to CPU if GPU not available.
"""

import warnings
import numpy as np
import pandas as pd
from typing import Tuple, List

# Try to import cuDF (GPU-accelerated pandas)
try:
    import cudf
    GPU_AVAILABLE = True
    print("✓ cuDF GPU acceleration available")
except ImportError:
    GPU_AVAILABLE = False
    cudf = None
    print("⚠️  cuDF not available, GPU acceleration disabled")

# Try to import cupy (GPU-accelerated numpy)
try:
    import cupy as cp
    CUPY_AVAILABLE = True
except ImportError:
    CUPY_AVAILABLE = False
    cp = None


class GPUValidator:
    """
    GPU-accelerated validation using NVIDIA RAPIDS cuDF.

    Provides 10-100x speedup for large datasets on NVIDIA GPUs.
    Automatically falls back to CPU if GPU not available.
    """

    def __init__(self):
        """Initialize GPU validator."""
        self.gpu_available = GPU_AVAILABLE
        self.device_type = "GPU" if GPU_AVAILABLE else "CPU"

        if GPU_AVAILABLE:
            # Check GPU memory
            try:
                import cupy as cp
                mempool = cp.get_default_memory_pool()
                print(f"GPU Memory Available: {mempool.free_bytes() / 1024**3:.2f} GB")
            except:
                pass

    def to_gpu(self, df: pd.DataFrame) -> 'cudf.DataFrame':
        """
        Transfer pandas DataFrame to GPU.

        Args:
            df: Pandas DataFrame

        Returns:
            cuDF DataFrame on GPU (or original if GPU not available)
        """
        if not self.gpu_available:
            return df

        try:
            # Convert to cuDF (GPU)
            gdf = cudf.from_pandas(df)
            return gdf
        except Exception as e:
            warnings.warn(f"Failed to transfer to GPU: {e}. Using CPU.")
            return df

    def to_cpu(self, gdf) -> pd.DataFrame:
        """
        Transfer cuDF DataFrame back to CPU.

        Args:
            gdf: cuDF DataFrame

        Returns:
            Pandas DataFrame
        """
        if not self.gpu_available or isinstance(gdf, pd.DataFrame):
            return gdf

        try:
            return gdf.to_pandas()
        except:
            return gdf

    def validate_proposal_numbers_gpu(self, data: pd.Series) -> Tuple[bool, List[int]]:
        """
        Validate proposal numbers on GPU.

        Args:
            data: Series of proposal numbers as strings

        Returns:
            Tuple of (is_valid, list of invalid indices)
        """
        if not self.gpu_available:
            # Fallback to CPU
            return self._validate_proposal_cpu(data)

        try:
            # Transfer to GPU
            gdata = cudf.Series(data)

            # Vectorized length check on GPU
            str_lens = gdata.str.len()
            invalid_mask = str_lens != 6

            # Get invalid indices
            invalid_indices = gdata[invalid_mask].index.to_pandas().tolist()

            return len(invalid_indices) == 0, invalid_indices

        except Exception as e:
            warnings.warn(f"GPU validation failed: {e}. Using CPU.")
            return self._validate_proposal_cpu(data)

    def validate_sample_names_gpu(self, data: pd.Series) -> Tuple[bool, List[int], pd.Series]:
        """
        Validate and clean sample names on GPU.

        Args:
            data: Series of sample names

        Returns:
            Tuple of (is_valid, list of invalid indices, cleaned data)
        """
        if not self.gpu_available:
            return self._validate_samples_cpu(data)

        try:
            # Transfer to GPU
            gdata = cudf.Series(data)

            # Pattern matching on GPU (cuDF supports regex)
            pattern = r'^[0-9a-zA-Z-_]{0,25}$'
            valid_mask = gdata.str.match(pattern)
            invalid_mask = ~valid_mask

            # Get invalid indices
            invalid_indices = gdata[invalid_mask].index.to_pandas().tolist()

            if len(invalid_indices) > 0:
                # Clean on GPU
                gdata_cleaned = gdata.str.replace(r'[^0-9a-zA-Z-_]', '_', regex=True)
                gdata_cleaned = gdata_cleaned.str[:25]  # Truncate

                # Transfer back to CPU
                cleaned_data = gdata_cleaned.to_pandas()
            else:
                cleaned_data = data

            return len(invalid_indices) == 0, invalid_indices, cleaned_data

        except Exception as e:
            warnings.warn(f"GPU validation failed: {e}. Using CPU.")
            return self._validate_samples_cpu(data)

    def find_duplicates_gpu(self, data: pd.Series) -> Tuple[bool, pd.Series]:
        """
        Find duplicate samples on GPU.

        Args:
            data: Series of sample names

        Returns:
            Tuple of (has_duplicates, duplicate mask)
        """
        if not self.gpu_available:
            return self._find_duplicates_cpu(data)

        try:
            # Transfer to GPU
            gdata = cudf.Series(data)

            # Find duplicates on GPU (much faster)
            dup_mask = gdata.duplicated(keep=False)

            # Transfer back
            dup_mask_cpu = dup_mask.to_pandas()

            return dup_mask_cpu.any(), dup_mask_cpu

        except Exception as e:
            warnings.warn(f"GPU validation failed: {e}. Using CPU.")
            return self._find_duplicates_cpu(data)

    def preprocess_dataframe_gpu(self, df: pd.DataFrame, columns: list) -> pd.DataFrame:
        """
        Preprocess entire dataframe on GPU.

        Args:
            df: DataFrame to preprocess
            columns: List of columns to process

        Returns:
            Preprocessed DataFrame
        """
        if not self.gpu_available or len(df) < 1000:
            # Not worth GPU overhead for small data
            return df

        try:
            print("🚀 Using GPU for preprocessing...")

            # Transfer to GPU
            gdf = cudf.from_pandas(df)

            # Batch string operations on GPU (much faster)
            for col in columns:
                if col in gdf.columns:
                    if col != 'samplename':
                        gdf[col] = gdf[col].astype(str).str.replace(r'\s+', '', regex=True)
                    else:
                        gdf[col] = gdf[col].astype(str).str.replace(r'(\.|s)+', '', regex=True)

            # Transfer back to CPU
            result = gdf.to_pandas()

            print("✓ GPU preprocessing complete")
            return result

        except Exception as e:
            warnings.warn(f"GPU preprocessing failed: {e}. Using CPU.")
            return df

    # CPU fallback methods
    def _validate_proposal_cpu(self, data: pd.Series) -> Tuple[bool, List[int]]:
        """CPU fallback for proposal validation."""
        str_lens = data.str.len()
        invalid_mask = str_lens != 6
        indices = data[invalid_mask].index.tolist()
        return len(indices) == 0, indices

    def _validate_samples_cpu(self, data: pd.Series) -> Tuple[bool, List[int], pd.Series]:
        """CPU fallback for sample validation."""
        pattern = r'^[0-9a-zA-Z-_]{0,25}$'
        non_matching_mask = ~data.str.match(pattern)
        invalid_indices = data[non_matching_mask].index.tolist()

        if len(invalid_indices) > 0:
            cleaned = data.str.replace(r'[^0-9a-zA-Z-_]', '_', regex=True).str[:25]
        else:
            cleaned = data

        return len(invalid_indices) == 0, invalid_indices, cleaned

    def _find_duplicates_cpu(self, data: pd.Series) -> Tuple[bool, pd.Series]:
        """CPU fallback for duplicate detection."""
        dup_mask = data.duplicated(keep=False)
        return dup_mask.any(), dup_mask

    def benchmark_gpu_vs_cpu(self, df: pd.DataFrame, num_runs: int = 3):
        """
        Benchmark GPU vs CPU validation.

        Args:
            df: DataFrame to validate
            num_runs: Number of runs for averaging
        """
        import time

        print("=" * 70)
        print(f"GPU vs CPU Benchmark ({len(df)} rows)")
        print("=" * 70)

        if not self.gpu_available:
            print("❌ GPU not available - cannot benchmark")
            return

        # CPU benchmark
        print("\n⏱️  CPU Validation...")
        cpu_times = []

        for i in range(num_runs):
            start = time.time()

            # CPU operations
            _ = df['samplename'].str.match(r'^[0-9a-zA-Z-_]{0,25}$')
            _ = df['samplename'].duplicated(keep=False)
            _ = df['proposalnum'].astype(str).str.len()

            elapsed = time.time() - start
            cpu_times.append(elapsed)
            print(f"   Run {i+1}: {elapsed:.3f}s")

        avg_cpu = sum(cpu_times) / len(cpu_times)

        # GPU benchmark
        print("\n⏱️  GPU Validation...")
        gpu_times = []

        for i in range(num_runs):
            start = time.time()

            # GPU operations
            gdf = cudf.from_pandas(df[['samplename', 'proposalnum']])
            _ = gdf['samplename'].str.match(r'^[0-9a-zA-Z-_]{0,25}$')
            _ = gdf['samplename'].duplicated(keep=False)
            _ = gdf['proposalnum'].astype(str).str.len()
            _ = gdf.to_pandas()  # Transfer back

            elapsed = time.time() - start
            gpu_times.append(elapsed)
            print(f"   Run {i+1}: {elapsed:.3f}s")

        avg_gpu = sum(gpu_times) / len(gpu_times)

        # Results
        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)
        print(f"CPU Average: {avg_cpu:.3f}s")
        print(f"GPU Average: {avg_gpu:.3f}s")

        if avg_gpu < avg_cpu:
            speedup = avg_cpu / avg_gpu
            print(f"✅ GPU is {speedup:.1f}x FASTER")
        else:
            slowdown = avg_gpu / avg_cpu
            print(f"❌ GPU is {slowdown:.1f}x SLOWER (overhead > gains for this dataset)")

        # Recommendation
        threshold_rows = 5000
        print(f"\n💡 Recommendation:")
        if len(df) < threshold_rows:
            print(f"   Dataset too small ({len(df)} < {threshold_rows} rows)")
            print(f"   GPU overhead exceeds gains - use CPU")
        elif avg_gpu < avg_cpu * 0.8:  # At least 20% faster
            print(f"   GPU provides significant speedup - USE GPU")
        else:
            print(f"   Marginal gains - CPU vectorization sufficient")

        print("=" * 70)


# Check GPU availability at import
def check_gpu_setup():
    """Check if GPU acceleration is properly set up."""
    print("\n" + "=" * 70)
    print("GPU ACCELERATION SETUP CHECK")
    print("=" * 70)

    # Check cuDF
    if GPU_AVAILABLE:
        print("✓ cuDF installed")

        try:
            import cudf
            # Try a simple operation
            test_df = cudf.DataFrame({'a': [1, 2, 3]})
            _ = test_df['a'].sum()
            print("✓ cuDF working correctly")
        except Exception as e:
            print(f"✗ cuDF error: {e}")

    else:
        print("✗ cuDF not installed")
        print("\nTo install cuDF:")
        print("  conda create -n rapids-env -c rapidsai -c conda-forge cudf python=3.10 cuda-version=11.8")
        print("  conda activate rapids-env")

    # Check cuPy
    if CUPY_AVAILABLE:
        print("✓ cuPy installed")
    else:
        print("✗ cuPy not installed (optional)")

    # Check CUDA
    try:
        import cupy as cp
        print(f"✓ CUDA version: {cp.cuda.runtime.runtimeGetVersion()}")
        print(f"✓ GPU: {cp.cuda.Device().name}")

        # Check memory
        mempool = cp.get_default_memory_pool()
        print(f"✓ GPU Memory: {mempool.free_bytes() / 1024**3:.2f} GB free")

    except:
        print("✗ CUDA not available or not configured")

    print("=" * 70)


if __name__ == "__main__":
    check_gpu_setup()
