#!/usr/bin/env python3
"""Offline conversion of exported targeting weights; never connects to a device."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

# Load the plugin's pure converter without importing its GUI or InVesalius.
_shared_path = Path(__file__).resolve().parents[2] / "src/neuronavigation/invesalius3/plugins/efield_targeting_area/voltage_conversion.py"
_spec = importlib.util.spec_from_file_location("_mtms_voltage_conversion", _shared_path)
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)
ConversionError = _shared.ConversionError
number = _shared.number
integer = _shared.integer
vector = _shared.vector
load_json = _shared.load_json
load_calibration = _shared.load_calibration
convert_export = _shared.convert_export
file_reference = _shared.file_reference

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="Exported targeting JSON")
    parser.add_argument("--config", type=Path, required=True, help="Channel/calibration conversion configuration JSON")
    parser.add_argument("--scale", type=float, required=True, help="Positive multiplier on exported weights; never inferred from MEPs")
    parser.add_argument("--target-index", type=int, action="append", help="Convert only this zero-based target index; repeat to select several")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_json(args.config)
        calibration = config.get("calibration_file")
        if not isinstance(calibration, str) or not calibration.strip():
            raise ConversionError("Set calibration_file in the conversion config")
        calibration = Path(calibration).expanduser()
        if not calibration.is_absolute():
            calibration = args.config.resolve().parent / calibration
        if any(args.output.resolve() == source.resolve() or (args.output.exists() and args.output.samefile(source))
               for source in (args.export, args.config, calibration)):
            raise ConversionError("Output must not overwrite an input file")
        report = convert_export(load_json(args.export), config, load_calibration(calibration), args.scale, args.target_index)
        report["created_at"] = datetime.now(timezone.utc).isoformat()
        report["sources"] = {"target_export": file_reference(args.export), "conversion_config": file_reference(args.config),
                             "calibration": file_reference(calibration)}
        text = json.dumps(report, indent=2, allow_nan=False) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w" if args.overwrite else "x", encoding="utf-8") as stream:
            stream.write(text)
        print(f"Wrote settings for {len(report['targets'])} target(s) to {args.output}; no device connection or stimulation.")
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"Conversion failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
