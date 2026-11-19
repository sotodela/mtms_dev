# Offline targeting weights → device settings

`convert_targeting_weights.py` reads the targeting plugin's exported JSON and writes proposed charge voltages and polarity flags for each optimized target. It does not import `MTMSApi`, connect to ROS, charge, or stimulate.

Copy `examples/weight_conversion_config.example.json` to your own configuration file. Replace the calibration file, basis dI/dt unit, and waveform identifier. Check every channel mapping, polarity correction, and voltage limit against your actual setup. The example's identity mapping, positive polarities, and 1490 V limit are illustrative values, not a verified configuration for your device.

```bash
python3 api/python/convert_targeting_weights.py targeting_export.json \
  --config conversion_config.json --scale 1 --output device_settings.json
```

Relative calibration paths resolve relative to the configuration file. Add `--target-index 0` to select one target (repeat for several). The default converts all target solutions and skips the one-hot `channel_reference` entries. Existing output files require `--overwrite`; input files cannot be overwritten.

## Conversion

For each exported basis channel:

```
model_didt_A_per_s = weight × basis_dIperdt × unit_factor × scale
signed_voltage_V = model_didt_A_per_s × polarity × volts_per_didt
charge_voltage_V = abs(signed_voltage_V)
reverse_polarity = signed_voltage_V < 0
```

`unit_factor` is 1 for `A/s` and 1,000,000 for `A/us`. The current export does not declare its physical dI/dt unit, so the configuration must explicitly supply the unit used by the E-field backend. Do not infer it from the basis value of 1.

`--scale` is a required positive, dimensionless multiplier. Use 1 to preserve the exported solution's intensity. A different scale changes the intended E-field amplitude by that factor under the linear model. The converter does not derive a stimulation intensity from MEP amplitudes.

This matches the voltage coefficient convention in MATLAB's `mTMS_toolkit.didt_to_volts`: coefficients have units V/(A/s), with a separate model-to-device polarity correction. The waveform identifier records the reference waveform matching those coefficients; it does not generate or validate a pulse waveform. These settings alone are not a complete stimulation program.

## Calibration and mapping

MATLAB `.mat` input must contain `calibration_data.volts_per_didt`. Reading it requires SciPy (`python3 -m pip install scipy` in your Python environment). JSON calibration needs only Python's standard library:

```json
{
  "didt_unit": "A/s",
  "volts_per_didt": [0.00002, 0.00003]
}
```

These two coefficients are synthetic examples. Use the coefficients from the calibration for your coil, cabinet and waveform.

Each configuration channel has:

| Field | Meaning |
|---|---|
| `basis_channel_index` | Zero-based channel index from the targeting export |
| `device_channel` | Zero-based device channel; output lists follow this order |
| `calibration_coil_number` | One-based index into `volts_per_didt`, matching MATLAB coil numbering |
| `polarity` | +1 or -1 model-to-device polarity correction |
| `max_voltage_v` | Explicit positive voltage limit for this channel |

All basis channels must be mapped exactly once. Coefficients must be finite and positive. The converter rejects voltage-limit violations without clipping or silently rescaling weights. It also rejects solutions spanning several coil poses: those cannot be realized as one pulse from a single stationary coil set.

## Output and later MEP matching

The output contains independent target entries with original/scaled weights, target coordinates when exported, coil pose, per-channel signed dI/dt, signed voltage, absolute charge voltage and polarity. Target/result indices and source file SHA-256 hashes preserve provenance. Voltages are unrounded; hardware quantization is deferred to a future acquisition layer.

Full cortical E-field arrays are not included in the current export or this output. Later MEP acquisition should attach a unique trial ID to the selected target/settings and store its matching E-field data separately, including the intensity scale and coil pose.

## Tests

```bash
python3 -m unittest discover -s api/python/tests -v
```

The MATLAB calibration test runs when SciPy is available; JSON conversion tests do not require SciPy or ROS.

## Aalto configuration in this workspace

The root `conversion_config.json` selects `data/aalto_mk3/calibration.mat` within the waveform approximator, using the Aalto site mapping. Run the command above from the MTMS root.

The default waveform is rising 2400 ticks (60 µs), hold 1200 ticks (30 µs), and falling [1560, 1560, 1600, 1600, 1776] ticks ([39, 39, 40, 40, 44.4] µs). These are the ROS default waveform and `sites/aalto/.env` settings. The calibration coefficient is the average ramp-up dI/dt conversion for the default monophasic pulse, not an instantaneous peak derivative conversion.

The basis unit is set to A/s: `set_dIperdt` forwards the inputs unchanged, the E-field wrapper passes their negative to the library's `minusdIPerdt` parameter, and its example uses 6600 × 10000 A/s. The negative sign implements Faraday's law and is not an additional device polarity correction. The compiled field library implementation is not available in this checkout, so this establishes the wrapper's intended SI convention rather than independently validating its numerical field scale.

Polarity profiles come from `api/matlab/mTMS_toolkit/coils/coil_specs_5coil_aalto_010925.csv`: `coilset_5_v230908` uses [1, -1, -1, -1, -1]; `coilset_5_v251022` uses [1, 1, 1, 1, 1]. The converter matches the exported coil model filename (optional extension), rejecting unknown or modified names. Profile entries override individual channel polarity fields. Output records the chosen profile and waveform reference.

The configuration maps five coils to device channels 0–4, matching the MATLAB default mapping. Aalto has six physical device channels; this file produces settings for the five-coil transducer only and does not assign channel 5. The 1490 V ceiling comes from the targeting code. Actual device wiring and current runtime waveform overrides cannot be established from these repository defaults.


The converter preserves the exported weights; it does not change the optimizer
or infer stimulation intensity. New window exports carry target normalization,
intensity and localization diagnostics. Review achieved fields and localization
status before interpreting a voltage report.

## Dry-run trial preview (no hardware connection)

```bash
python3 api/python/dry_run_targeting_trial.py device_settings.json \
  --config conversion_config.json --output trial_preview.json
```

Use `--target-index 0` (repeatable) to preview particular targets. Each selected
target is an independent proposed trial, not a timed sequence. All selected
settings are checked before any commands are printed or output is written.
Output JSON must not already exist. There is no execute/stimulate option.

Checks include finite/nonnegative charge voltages, the lesser of configured and
exported voltage limits and the repository's 1490 V ceiling, channel ordering and
mapping, signed-voltage/polarity agreement, weight and dI/dt arithmetic, matching
waveform references, and matching configuration provenance hashes when present.
The configuration must describe the Aalto five-coil array on channels 0–4.
The preview adds an explicit 0 V charge/discharge setting for device channel 5
(the sixth physical channel) and schedules no pulse for it. A sixth supplied
channel is accepted only when zero with false polarity. The default waveform
configuration contains only five fall durations, so the preview uses per-channel
pulse commands rather than `send_default_pulse_to_all_channels`.

This is settings consistency validation. Calibration coefficients are checked
arithmetically against the settings but are not reloaded or physically measured.
The preview does not establish physical wiring, actual waveform state, E-field
units/accuracy, target amplitude, focality, or physiological suitability. Source
error and achieved-field metadata are shown if available; older settings may
lack them. A passing report always declares `hardware_ready: false` and
`physical_field_validation: "not performed"`.

Commands are inert display text: the waveform is an explicit placeholder, and
session setup, charge-completion checks, trigger execution, and acquisition are
not implemented. The script imports no MTMS API or ROS package and works with
Python's standard library alone. It does not connect to any device or emit a
trigger. No helper in this script can execute the printed commands.

For whole-cortex target verification from final voltages, use **Validate voltage
settings** in the InVesalius targeting window. It recalculates the field in the
loaded model; a dry-run command preview alone does not perform that check.

## Export without the terminal

The targeting window now provides **Export voltage JSON**. It uses the same
conversion implementation as this CLI, packaged in the independent plugin as
`voltage_conversion.py`. The CLI therefore runs from the MTMS workspace with
that plugin checkout available; it does not import the plugin GUI.

The window defaults to its bundled Aalto configuration and reference calibration
coefficients. It normalizes each target to 1 V/m and exports that reference
multiplied by the window intensity. The conversion stage adds no further scale.
It exports all optimized targets and embeds the source snapshot with a hash.
No separate targeting-area file is needed for the in-window workflow. Click
**Validate voltage settings** afterward; the saved file is preselected.


For new normalized window exports, the exported result weights already contain
the intensity multiplier. Use CLI `--scale 1` to preserve that exported intensity;
any other CLI scale is an **additional** multiplier. Normalization and intensity
metadata are carried into voltage settings so validation can recover the expected
amplitude without applying the intensity twice. Old exported results are not
automatically normalized by the CLI; prepare new results in the plugin first.
