#!/usr/bin/env python3
"""
Test script to measure if parallel validation would help your dataset.

Usage:
    python test_parallel_speed.py path/to/your/excel/file.xlsx
"""

import sys
import time
import pandas as pd
from pathlib import Path

def test_parallel_benefit(excel_path: str):
    """
    Test if parallel validation would benefit your dataset.

    Args:
        excel_path: Path to your Excel file
    """
    print("=" * 70)
    print("PARALLEL VALIDATION SPEED TEST")
    print("=" * 70)

    # Load data
    print(f"\n📂 Loading: {excel_path}")
    try:
        df = pd.read_excel(excel_path)
        print(f"✓ Loaded {len(df)} rows, {len(df.columns)} columns")
    except Exception as e:
        print(f"✗ Error loading file: {e}")
        return

    # Check if worth testing
    row_count = len(df)
    print(f"\n📊 Dataset size: {row_count} rows")

    if row_count < 1000:
        print("⚠️  Dataset is small (< 1,000 rows)")
        print("   Current optimizations are sufficient")
        print("   Parallel validation NOT recommended")
        return

    # Import validation modules
    try:
        from utils.parallel_validation import ParallelValidator, benchmark_parallel_vs_sequential
        print("✓ Parallel validation module available")
    except ImportError as e:
        print(f"✗ Cannot import parallel validation: {e}")
        print("  Make sure parallel_validation.py is in utils/")
        return

    # Check CPU count
    import multiprocessing as mp
    cpu_count = mp.cpu_count()
    print(f"💻 CPU cores available: {cpu_count}")

    if cpu_count < 2:
        print("⚠️  Only 1 CPU core detected")
        print("   Parallel validation NOT recommended")
        return

    # Prepare data for validation
    print("\n🔧 Preparing data for validation test...")

    # Extract required columns if they exist
    required_cols = ['puckname', 'position', 'samplename', 'proposalnum']
    missing_cols = [col for col in required_cols if col not in df.columns]

    if missing_cols:
        print(f"⚠️  Missing columns: {missing_cols}")
        print("   Creating synthetic test columns...")

        # Create synthetic data for testing
        if 'samplename' not in df.columns:
            df['samplename'] = [f'Sample_{i:05d}' for i in range(len(df))]
        if 'proposalnum' not in df.columns:
            df['proposalnum'] = ['123456'] * len(df)
        if 'puckname' not in df.columns:
            df['puckname'] = [f'PUCK-{i//16 + 1:03d}' for i in range(len(df))]
        if 'position' not in df.columns:
            df['position'] = [(i % 16) + 1 for i in range(len(df))]

    # Run benchmark
    print("\n⏱️  Running benchmark (3 runs each)...")
    print("   This may take a minute...\n")

    benchmark_parallel_vs_sequential(df, num_runs=3)

    # Recommendation
    print("\n" + "=" * 70)
    print("RECOMMENDATION")
    print("=" * 70)

    validator = ParallelValidator()
    if validator.should_use_parallel(row_count):
        print("✅ ENABLE parallel validation for this dataset size")
        print("\nHow to enable:")
        print("1. Edit import_pucks.py, line ~420:")
        print("   self.model = PuckPandasModel(data, use_parallel=True)")
        print("\n2. Or add to config.yaml:")
        print("   use_parallel_validation: true")
    else:
        print("❌ KEEP sequential validation (current optimizations sufficient)")
        print(f"\n   Dataset has {row_count} rows (threshold: 5,000)")
        print("   Parallel overhead would exceed gains")

    print("\n" + "=" * 70)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python test_parallel_speed.py path/to/excel/file.xlsx")
        print("\nOr test with synthetic data:")
        print("python test_parallel_speed.py --synthetic 10000")
        sys.exit(1)

    if sys.argv[1] == "--synthetic":
        # Generate synthetic data for testing
        try:
            size = int(sys.argv[2]) if len(sys.argv) > 2 else 10000
        except ValueError:
            size = 10000

        print(f"Generating synthetic dataset with {size} rows...")

        df = pd.DataFrame({
            'puckname': [f'PUCK-{i//16 + 1:03d}' for i in range(size)],
            'position': [(i % 16) + 1 for i in range(size)],
            'samplename': [f'Sample_{i:05d}' for i in range(size)],
            'proposalnum': ['123456'] * size,
        })

        # Save temporary file
        temp_file = Path("temp_synthetic_data.xlsx")
        df.to_excel(temp_file, index=False)
        print(f"Saved to: {temp_file}\n")

        test_parallel_benefit(str(temp_file))

        # Cleanup
        temp_file.unlink()

    else:
        # Test with user-provided file
        excel_path = sys.argv[1]

        if not Path(excel_path).exists():
            print(f"Error: File not found: {excel_path}")
            sys.exit(1)

        test_parallel_benefit(excel_path)


if __name__ == "__main__":
    main()
