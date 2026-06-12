import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.test_outlets import ts1_path, scenarios
from src.usg_model_builder import run_simulation

cfg = scenarios["No_Outlet"]

def mock_run(*args, **kwargs):
    print("MOCK RUN!")
    sys.exit(0)

import subprocess
subprocess.run = mock_run

try:
    run_simulation(ts1_path, cfg)
except Exception as e:
    print(f"Error: {e}")
