import argparse
import json
import sys
from pathlib import Path

# Ensure we can import from src/
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from main_phase3_step32_time_varying import run_phase3_step32_with_config  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Run Phase3 Step32 with a JSON config and TS1 file")
    p.add_argument("--config", required=True, help="Path to JSON config file")
    p.add_argument("--ts1", required=False, help="Path to TS1 hydrograph file (optional)")
    args = p.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"Config not found: {cfg_path}", file=sys.stderr)
        sys.exit(2)

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    ts1_path = args.ts1
    ok, summary, out_dir = run_phase3_step32_with_config(ts1_path, cfg)
    # Normalize outputs
    if isinstance(summary, dict):
        print(json.dumps(summary, indent=2))
    else:
        print(str(summary))
    print(f"output_dir={out_dir}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
