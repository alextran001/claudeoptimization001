#!/usr/bin/env python3
"""
Profile validation to find actual bottlenecks.
This will show WHERE the time is being spent.

Usage:
    python profile_validation.py path/to/excel/file.xlsx
"""

import cProfile
import pstats
import io
import sys
import time
from pathlib import Path
import pandas as pd

def profile_validation(excel_path):
    """Profile the validation process to find bottlenecks."""

    print("=" * 70)
    print("VALIDATION PROFILER - Finding Bottlenecks")
    print("=" * 70)

    # Load data
    print(f"\n📂 Loading: {excel_path}")
    df = pd.read_excel(excel_path)
    print(f"✓ Loaded {len(df)} rows")

    # Import the model
    from utils.pandas_model import PuckPandasModel

    # Create profiler
    profiler = cProfile.Profile()

    # Profile preprocessing
    print("\n🔍 Profiling preprocessData()...")
    model = PuckPandasModel(df)

    profiler.enable()
    start = time.time()

    try:
        model.preprocessData()
    except Exception as e:
        print(f"Note: {e}")

    preprocess_time = time.time() - start
    profiler.disable()

    print(f"⏱️  preprocessData took: {preprocess_time:.2f} seconds")

    # Show top time consumers in preprocessing
    print("\n📊 Top 10 time consumers in preprocessData:")
    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
    ps.print_stats(20)

    # Parse and display
    lines = s.getvalue().split('\n')
    for line in lines[5:25]:  # Show top 20 lines
        if line.strip():
            print(f"   {line}")

    # Profile validation
    print("\n🔍 Profiling validateData()...")
    profiler2 = cProfile.Profile()

    # Mock config
    config = {
        'disable_whitelist': True,
        'disable_blacklist': True,
        'disable_etchedlist': True
    }

    profiler2.enable()
    start = time.time()

    try:
        model.validateData(config)
    except Exception as e:
        print(f"Note: {e}")

    validate_time = time.time() - start
    profiler2.disable()

    print(f"⏱️  validateData took: {validate_time:.2f} seconds")

    # Show top time consumers in validation
    print("\n📊 Top 10 time consumers in validateData:")
    s2 = io.StringIO()
    ps2 = pstats.Stats(profiler2, stream=s2).sort_stats('cumulative')
    ps2.print_stats(20)

    # Parse and display
    lines2 = s2.getvalue().split('\n')
    for line in lines2[5:25]:
        if line.strip():
            print(f"   {line}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total time: {preprocess_time + validate_time:.2f} seconds")
    print(f"  - preprocessData: {preprocess_time:.2f}s ({preprocess_time/(preprocess_time+validate_time)*100:.1f}%)")
    print(f"  - validateData:   {validate_time:.2f}s ({validate_time/(preprocess_time+validate_time)*100:.1f}%)")

    # Save detailed profile
    print("\n💾 Saving detailed profile to 'profile_output.txt'...")
    with open('profile_output.txt', 'w') as f:
        ps_combined = pstats.Stats(profiler, profiler2, stream=f)
        ps_combined.sort_stats('cumulative')
        ps_combined.print_stats()
    print("✓ Detailed profile saved")

    # Identify bottlenecks
    print("\n🔍 Bottleneck Analysis:")

    # Check for common bottlenecks
    profile_text = s.getvalue() + s2.getvalue()

    bottlenecks = []

    if 'to_excel' in profile_text or 'ExcelWriter' in profile_text:
        bottlenecks.append("📝 Excel I/O operations (writing files)")

    if 'processEvents' in profile_text:
        bottlenecks.append("🖥️  Qt GUI updates (processEvents)")

    if 'dataChanged.emit' in profile_text or 'emit' in profile_text:
        bottlenecks.append("📡 Qt signal emissions")

    if 'read_excel' in profile_text:
        bottlenecks.append("📂 Excel file reading")

    if 'astype' in profile_text and profile_text.count('astype') > 5:
        bottlenecks.append("🔄 Type conversions (astype)")

    if 'apply' in profile_text or 'map' in profile_text:
        bottlenecks.append("🐌 Non-vectorized operations (apply/map)")

    if bottlenecks:
        print("\n   Detected bottlenecks:")
        for b in bottlenecks:
            print(f"   - {b}")
    else:
        print("   No obvious bottlenecks detected in common areas")

    print("\n💡 Check 'profile_output.txt' for detailed analysis")
    print("=" * 70)


def profile_with_gui(excel_path):
    """Profile with actual GUI application (more realistic)."""

    print("\n" + "=" * 70)
    print("PROFILING WITH GUI APPLICATION")
    print("=" * 70)

    from qtpy import QtWidgets
    import sys

    # Create Qt application
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    # Import main window
    from import_pucks import ControlMain
    from pathlib import Path

    # Find config
    config_path = Path("config.yaml")
    if not config_path.exists():
        config_path = Path("config/config.yaml")

    if not config_path.exists():
        print("⚠️  No config.yaml found, cannot profile GUI application")
        return

    print("🚀 Starting GUI application...")

    profiler = cProfile.Profile()
    profiler.enable()

    start = time.time()

    # Create main window
    window = ControlMain(config_path=config_path)

    # Simulate importing Excel
    # This would need to be manually triggered

    elapsed = time.time() - start
    profiler.disable()

    print(f"⏱️  GUI initialization: {elapsed:.2f}s")

    # Save profile
    with open('profile_gui.txt', 'w') as f:
        ps = pstats.Stats(profiler, stream=f)
        ps.sort_stats('cumulative')
        ps.print_stats()

    print("💾 GUI profile saved to 'profile_gui.txt'")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python profile_validation.py path/to/excel/file.xlsx")
        print("\nOr use test data:")
        print("python profile_validation.py data/PSL-20250524.xlsx")
        sys.exit(1)

    excel_path = sys.argv[1]

    if not Path(excel_path).exists():
        print(f"Error: File not found: {excel_path}")
        sys.exit(1)

    profile_validation(excel_path)
