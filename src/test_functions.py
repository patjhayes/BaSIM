"""
Test script to verify core functions before running the full model
"""
import sys
import os
sys.path.append(os.path.dirname(__file__))

from main import parse_ts1_file, select_ts1_file
import numpy as np

def test_ts1_parser():
    """Test the TS1 file parser"""
    print("Testing TS1 parser...")
    
    # Test with a known file
    ts1_file = r"C:\Users\patri\OneDrive\BaSIM\External\OUTPUT\cat1_Catchments_1% AEP, 1 hour burst, Storm 5.ts1"
    
    if not os.path.exists(ts1_file):
        print("❌ Test file not found")
        return False
        
    try:
        data = parse_ts1_file(ts1_file)
        print(f"✅ Successfully parsed {len(data)} data points")
        print(f"   Duration: {data[-1,0]/3600:.2f} hours")
        print(f"   Peak flow: {np.max(data[:,1]):.3f} m³/s")
        return True
    except Exception as e:
        print(f"❌ Parser failed: {e}")
        return False

def test_imports():
    """Test that all required packages can be imported"""
    print("Testing package imports...")
    
    try:
        import flopy
        print(f"✅ flopy {flopy.__version__}")
    except ImportError as e:
        print(f"❌ flopy import failed: {e}")
        return False
        
    try:
        import matplotlib
        print(f"✅ matplotlib {matplotlib.__version__}")
    except ImportError as e:
        print(f"❌ matplotlib import failed: {e}")
        return False
        
    try:
        import numpy
        print(f"✅ numpy {numpy.__version__}")
    except ImportError as e:
        print(f"❌ numpy import failed: {e}")
        return False
        
    try:
        import pandas
        print(f"✅ pandas {pandas.__version__}")
    except ImportError as e:
        print(f"❌ pandas import failed: {e}")
        return False
        
    return True

def test_modflow_executable():
    """Test that MODFLOW 6 executable is accessible"""
    print("Testing MODFLOW 6 executable...")
    
    mf6_exe = r"C:\Users\patri\OneDrive\Documents\mf6.6.2_win64\bin\mf6.exe"
    
    if not os.path.exists(mf6_exe):
        print(f"❌ MODFLOW 6 executable not found at {mf6_exe}")
        return False
        
    print(f"✅ MODFLOW 6 executable found")
    return True

def test_directories():
    """Test that required directories exist"""
    print("Testing directory structure...")
    
    base_dir = r"C:\Users\patri\OneDrive\BaSIM"
    required_dirs = [
        os.path.join(base_dir, "src"),
        os.path.join(base_dir, "model_output"),
        os.path.join(base_dir, "External", "OUTPUT")
    ]
    
    all_exist = True
    for dir_path in required_dirs:
        if os.path.exists(dir_path):
            print(f"✅ {dir_path}")
        else:
            print(f"❌ {dir_path} - does not exist")
            all_exist = False
            
    return all_exist

def main():
    """Run all tests"""
    print("Basin Infiltration Modeling - System Tests")
    print("=" * 50)
    
    tests = [
        ("Package Imports", test_imports),
        ("Directory Structure", test_directories),
        ("MODFLOW 6 Executable", test_modflow_executable),
        ("TS1 File Parser", test_ts1_parser),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        result = test_func()
        results.append((test_name, result))
    
    print("\n" + "=" * 50)
    print("Test Summary:")
    all_passed = True
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {test_name}: {status}")
        if not result:
            all_passed = False
    
    if all_passed:
        print("\n🎉 All tests passed! Ready to run the basin model.")
    else:
        print("\n⚠️  Some tests failed. Please address issues before running the model.")

if __name__ == "__main__":
    main()
