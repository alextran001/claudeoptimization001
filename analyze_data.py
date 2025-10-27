#!/usr/bin/env python3
"""
Quick analysis of your data file to determine if parallel validation would help.
Run this in your Python environment that has pandas installed.
"""

import pandas as pd
import time
import sys

def analyze_file(filepath):
    """Analyze the data file and provide recommendations."""

    print("=" * 70)
    print("DATA FILE ANALYSIS")
    print("=" * 70)

    # Load the file
    print(f"\n📂 Loading: {filepath}")
    try:
        start = time.time()
        df = pd.read_excel(filepath)
        load_time = time.time() - start
        print(f"✓ Loaded in {load_time:.2f} seconds")
    except Exception as e:
        print(f"✗ Error: {e}")
        return

    # Basic info
    print(f"\n📊 Dataset Information:")
    print(f"   Rows: {len(df)}")
    print(f"   Columns: {len(df.columns)}")
    print(f"   Memory usage: {df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB")

    # Show columns
    print(f"\n📋 Columns found:")
    for i, col in enumerate(df.columns, 1):
        print(f"   {i}. {col}")

    # Estimate validation time
    row_count = len(df)

    # Based on benchmarks: ~100 rows/second with current optimizations
    estimated_sequential = row_count / 100

    # Parallel would be faster but has overhead
    if row_count < 5000:
        parallel_overhead = 1.5  # seconds
        estimated_parallel = (row_count / 300) + parallel_overhead
    else:
        parallel_overhead = 2  # seconds
        estimated_parallel = (row_count / 300) + parallel_overhead

    print(f"\n⏱️  Estimated Validation Time:")
    print(f"   Sequential (current): ~{estimated_sequential:.1f} seconds")
    print(f"   Parallel (4 cores):   ~{estimated_parallel:.1f} seconds")

    # Recommendation
    print("\n" + "=" * 70)
    print("RECOMMENDATION")
    print("=" * 70)

    if row_count < 1000:
        print("✅ Dataset is SMALL (< 1,000 rows)")
        print(f"   Current optimizations are PERFECT")
        print(f"   Expected validation time: {estimated_sequential:.1f} seconds")
        print(f"\n   ❌ DO NOT use parallel validation")
        print(f"      Overhead would make it slower!")

    elif row_count < 5000:
        print("✅ Dataset is MEDIUM (1,000-5,000 rows)")
        print(f"   Current optimizations should be sufficient")
        print(f"   Expected validation time: {estimated_sequential:.1f} seconds")
        print(f"\n   ⚠️  Parallel validation: marginal gains")
        print(f"      Would save ~{max(0, estimated_sequential - estimated_parallel):.1f} seconds")
        print(f"      Recommendation: SKIP parallel (not worth complexity)")

    elif row_count < 10000:
        print("⚠️  Dataset is LARGE (5,000-10,000 rows)")
        print(f"   Current optimizations: ~{estimated_sequential:.1f} seconds")
        print(f"   Parallel validation: ~{estimated_parallel:.1f} seconds")
        print(f"\n   ✅ Parallel validation: MODERATE gains")
        print(f"      Would save ~{estimated_sequential - estimated_parallel:.1f} seconds")
        speedup = estimated_sequential / estimated_parallel
        print(f"      Speedup: {speedup:.1f}x")
        print(f"\n      Recommendation: TEST IT")
        print(f"      Run: python test_parallel_speed.py data/PSL-20250524.xlsx")

    else:
        print("🚀 Dataset is VERY LARGE (10,000+ rows)")
        print(f"   Current optimizations: ~{estimated_sequential:.1f} seconds")
        print(f"   Parallel validation: ~{estimated_parallel:.1f} seconds")
        print(f"\n   ✅✅ Parallel validation: SIGNIFICANT gains")
        print(f"      Would save ~{estimated_sequential - estimated_parallel:.1f} seconds")
        speedup = estimated_sequential / estimated_parallel
        print(f"      Speedup: {speedup:.1f}x")
        print(f"\n      Recommendation: DEFINITELY USE PARALLEL")
        print(f"      Enable with: use_parallel=True")

    print("\n" + "=" * 70)
    print()

    # Check for required columns
    required_cols = ['puckname', 'position', 'samplename', 'proposalnum']
    missing = [col for col in required_cols if col.lower() not in [c.lower() for c in df.columns]]

    if missing:
        print(f"⚠️  Note: Missing required columns: {missing}")
        print(f"   These will be created during import\n")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyze_file(sys.argv[1])
    else:
        # Default to the data file
        analyze_file("data/PSL-20250524.xlsx")
