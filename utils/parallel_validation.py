"""
Parallel Validation Module using Multiprocessing

This module provides multiprocessing support for validation operations.
Only use for large datasets (10,000+ rows) where overhead is justified.

WARNING: Qt signals and DataFrame modifications MUST remain on main thread.
"""

import multiprocessing as mp
from multiprocessing import Pool
from functools import partial
import pandas as pd
import numpy as np
from typing import List, Tuple, Set
import re

# Import pre-compiled regex patterns
from utils.pandas_model import (
    REGEX_SAMPLE_VALID,
    REGEX_NON_DIGITS,
    REGEX_SAMPLE_INVALID_CHARS
)


class ParallelValidator:
    """
    Parallel validation using multiprocessing.

    Only performs READ-ONLY validations in parallel.
    DataFrame modifications still happen on main thread.
    """

    def __init__(self, num_processes: int = None):
        """
        Initialize parallel validator.

        Args:
            num_processes: Number of processes to use. Defaults to CPU count - 1.
        """
        if num_processes is None:
            # Leave one CPU for main thread and GUI
            num_processes = max(1, mp.cpu_count() - 1)
        self.num_processes = num_processes

    def should_use_parallel(self, row_count: int) -> bool:
        """
        Determine if dataset is large enough to benefit from parallelization.

        Args:
            row_count: Number of rows in dataset

        Returns:
            True if parallel processing is recommended
        """
        # Only use parallel for datasets with 5000+ rows
        # Below this, overhead > gains
        return row_count >= 5000

    def validate_proposal_numbers_parallel(self, data: pd.Series) -> Tuple[bool, List[int]]:
        """
        Validate proposal numbers in parallel (read-only).

        Args:
            data: Series of proposal numbers

        Returns:
            Tuple of (is_valid, list of invalid indices)
        """
        # Check if all same (must be done in main thread)
        if data.nunique() > 1:
            return False, []

        # Split data into chunks
        chunks = np.array_split(data, self.num_processes)

        # Validate each chunk in parallel
        with Pool(self.num_processes) as pool:
            results = pool.map(_validate_proposal_chunk, chunks)

        # Merge results
        invalid_indices = []
        for indices in results:
            invalid_indices.extend(indices)

        return len(invalid_indices) == 0, invalid_indices

    def validate_sample_names_parallel(self, data: pd.Series) -> Tuple[bool, List[int]]:
        """
        Validate sample names in parallel (read-only check).

        Args:
            data: Series of sample names

        Returns:
            Tuple of (is_valid, list of invalid indices)
        """
        # Split data into chunks
        chunks = np.array_split(data, self.num_processes)

        # Validate each chunk in parallel
        with Pool(self.num_processes) as pool:
            results = pool.map(_validate_sample_names_chunk, chunks)

        # Merge results
        invalid_indices = []
        for indices in results:
            invalid_indices.extend(indices)

        return len(invalid_indices) == 0, invalid_indices

    def find_duplicates_parallel(self, data: pd.Series) -> Tuple[bool, Set[str], pd.Series]:
        """
        Find duplicate samples in parallel.

        NOTE: This only FINDS duplicates. Renaming must happen on main thread.

        Args:
            data: Series of sample names

        Returns:
            Tuple of (has_duplicates, set of duplicate names, duplicate mask)
        """
        # Use pandas duplicated() - already optimized and vectorized
        # Multiprocessing won't help here due to overhead
        dup_mask = data.duplicated(keep=False)
        duplicated_data = data[dup_mask]

        return len(duplicated_data) > 0, set(duplicated_data.unique()), dup_mask

    def validate_all_parallel(self, df: pd.DataFrame) -> dict:
        """
        Perform all read-only validations in parallel.

        Args:
            df: DataFrame to validate

        Returns:
            Dictionary with validation results
        """
        if not self.should_use_parallel(len(df)):
            # Dataset too small, return None to use sequential validation
            return None

        results = {}

        # Run independent validations in parallel using Pool
        with Pool(self.num_processes) as pool:
            # Submit all validation tasks
            proposal_future = pool.apply_async(
                _validate_proposal_chunk,
                (df['proposalnum'].astype(str).str.replace(REGEX_NON_DIGITS, "", regex=True),)
            )
            sample_name_future = pool.apply_async(
                _validate_sample_names_chunk,
                (df['samplename'],)
            )
            empty_future = pool.apply_async(
                _check_empty_chunk,
                (df['samplename'],)
            )

            # Collect results
            results['proposal_invalid_indices'] = proposal_future.get()
            results['sample_name_invalid_indices'] = sample_name_future.get()
            results['empty_indices'] = empty_future.get()

        # Check duplicates (fast, don't parallelize)
        results['duplicate_mask'] = df['samplename'].duplicated(keep=False)

        # Check duplicate puck positions (fast, don't parallelize)
        results['duplicate_puck_pos'] = df.duplicated(subset=["puckname", "position"], keep=False)

        return results


# Worker functions (must be at module level for pickling)

def _validate_proposal_chunk(chunk: pd.Series) -> List[int]:
    """
    Validate proposal numbers in a chunk.

    Args:
        chunk: Series chunk to validate

    Returns:
        List of invalid indices
    """
    # Vectorized length check
    str_lens = chunk.str.len()
    invalid_mask = str_lens != 6
    return chunk[invalid_mask].index.tolist()


def _validate_sample_names_chunk(chunk: pd.Series) -> List[int]:
    """
    Validate sample names in a chunk.

    Args:
        chunk: Series chunk to validate

    Returns:
        List of invalid indices
    """
    # Vectorized regex matching
    non_matching_mask = ~chunk.str.match(REGEX_SAMPLE_VALID)
    return chunk[non_matching_mask].index.tolist()


def _check_empty_chunk(chunk: pd.Series) -> List[int]:
    """
    Check for empty samples in a chunk.

    Args:
        chunk: Series chunk to check

    Returns:
        List of empty indices
    """
    empty_mask = chunk.isna()
    return chunk[empty_mask].index.tolist()


def _check_duplicates_chunk(chunk: pd.Series) -> Set[str]:
    """
    Find duplicate values in a chunk.

    Args:
        chunk: Series chunk to check

    Returns:
        Set of duplicate values
    """
    dup_mask = chunk.duplicated(keep=False)
    return set(chunk[dup_mask].unique())


# Example usage function
def benchmark_parallel_vs_sequential(df: pd.DataFrame, num_runs: int = 3):
    """
    Benchmark parallel vs sequential validation.

    Args:
        df: DataFrame to validate
        num_runs: Number of runs for averaging
    """
    import time

    print(f"Benchmarking validation on {len(df)} rows...")
    print(f"CPU count: {mp.cpu_count()}")

    validator = ParallelValidator()

    # Sequential timing
    sequential_times = []
    for i in range(num_runs):
        start = time.time()

        # Simulate sequential validation
        _ = df['proposalnum'].astype(str).str.len() != 6
        _ = ~df['samplename'].str.match(REGEX_SAMPLE_VALID)
        _ = df['samplename'].isna()
        _ = df['samplename'].duplicated(keep=False)

        elapsed = time.time() - start
        sequential_times.append(elapsed)

    avg_sequential = sum(sequential_times) / len(sequential_times)
    print(f"Sequential average: {avg_sequential:.3f} seconds")

    # Parallel timing
    if validator.should_use_parallel(len(df)):
        parallel_times = []
        for i in range(num_runs):
            start = time.time()
            _ = validator.validate_all_parallel(df)
            elapsed = time.time() - start
            parallel_times.append(elapsed)

        avg_parallel = sum(parallel_times) / len(parallel_times)
        speedup = avg_sequential / avg_parallel

        print(f"Parallel average: {avg_parallel:.3f} seconds")
        print(f"Speedup: {speedup:.2f}x")
    else:
        print("Dataset too small for parallel processing (< 5000 rows)")
        print("Overhead would exceed gains")


if __name__ == "__main__":
    # Test with sample data
    print("Parallel Validation Module")
    print("=" * 50)

    # Create test dataset
    test_sizes = [100, 1000, 5000, 10000]

    for size in test_sizes:
        df = pd.DataFrame({
            'puckname': [f'PUCK-{i//16 + 1:03d}' for i in range(size)],
            'position': [(i % 16) + 1 for i in range(size)],
            'samplename': [f'Sample_{i:05d}' for i in range(size)],
            'proposalnum': ['123456'] * size,
        })

        print(f"\n--- Dataset size: {size} rows ---")
        benchmark_parallel_vs_sequential(df, num_runs=3)
