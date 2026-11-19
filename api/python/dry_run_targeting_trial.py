#!/usr/bin/env python3
"""Validate and preview Aalto settings locally. No API imports or execution mode."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

from convert_targeting_weights import ConversionError, integer, load_json, number


def close(actual, expected, label):
    actual = number(actual, label)
    if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12):
        raise ConversionError(f"{label} is inconsistent: {actual:g} versus {expected:g}")


def boolean(value, label):
    if not isinstance(value, bool):
        raise ConversionError(f"{label} must be a JSON boolean")
    return value


def preview_settings(settings, config, target_indices=None):
    """Build an inert command plan after checking every selected target."""
    if settings.get('schema') != 'mtms.targeting_device_settings.v1':
        raise ConversionError('Expected converted device settings JSON, not the plugin export')
    if config.get('schema') != 'mtms.weight_conversion_config.v1':
        raise ConversionError('Expected conversion configuration schema v1')
    if settings.get('conversion_only') is not True or settings.get('stimulation_performed') is not False:
        raise ConversionError('Input must be marked conversion_only=true and stimulation_performed=false')
    unit = settings.get('basis_didt_unit')
    if unit not in ('A/s', 'A/us') or unit != config.get('basis_didt_unit') or settings.get('calibration_didt_unit') != 'A/s':
        raise ConversionError('Settings and configuration must agree on dI/dt units')
    scale = number(settings.get('weight_scale'), 'weight_scale', positive=True)
    waveform = settings.get('waveform_id')
    if not isinstance(waveform, str) or not waveform or waveform.startswith('REPLACE') or waveform != config.get('waveform_id'):
        raise ConversionError('A matching, non-placeholder waveform_id is required')
    reference = config.get('waveform_reference')
    if not isinstance(reference, dict) or reference.get('phases') != ['rising', 'hold', 'falling']:
        raise ConversionError('Aalto preview requires the configured three-phase waveform_reference')
    tick = number(reference.get('tick_duration_s'), 'tick_duration_s', positive=True)
    if tick != 25e-9:
        raise ConversionError('Expected Aalto 25 ns waveform ticks')
    rise = integer(reference.get('rising_ticks'), 'rising_ticks', minimum=1)
    hold = integer(reference.get('hold_ticks'), 'hold_ticks', minimum=1)
    falls = reference.get('falling_ticks_by_device_channel')
    if not isinstance(falls, list) or len(falls) != 5:
        raise ConversionError('Expected five fall durations for Aalto transducer channels 0-4')
    falls = [integer(v, 'falling_ticks', minimum=1) for v in falls]
    if any(v > 65535 for v in [rise, hold, *falls]):
        raise ConversionError('Waveform duration exceeds the uint16 tick range')
    if settings.get('waveform_reference') is not None and settings['waveform_reference'] != reference:
        raise ConversionError('Settings waveform reference differs from configuration')
    mapping = config.get('channels')
    if not isinstance(mapping, list) or len(mapping) != 5:
        raise ConversionError('Aalto five-coil configuration must map five channels')
    by_device = {}
    for item in mapping:
        channel = integer(item.get('device_channel'), 'configured device_channel')
        if channel not in range(5) or channel in by_device:
            raise ConversionError('Configuration must map device channels 0-4 exactly once')
        number(item.get('max_voltage_v'), 'configured max_voltage_v', positive=True)
        by_device[channel] = item
    profiles = config.get('polarity_by_coil_model')
    profile = settings.get('polarity_profile')
    if profiles is not None and profile not in profiles:
        raise ConversionError('Settings polarity profile is not defined in configuration')
    selected = None if target_indices is None else {integer(v, 'selected target_index') for v in target_indices}
    targets = settings.get('targets')
    if not isinstance(targets, list) or not targets:
        raise ConversionError('Settings have no targets')
    plans, seen = [], set()
    for target in targets:
        index = integer(target.get('target_index'), 'target_index')
        if index in seen:
            raise ConversionError(f'Duplicate target_index {index}')
        seen.add(index)
        if selected is not None and index not in selected:
            continue
        rows = target.get('channels')
        voltages, polarities = target.get('target_voltages'), target.get('reverse_polarities')
        if not isinstance(rows, list) or len(rows) not in (5, 6):
            raise ConversionError('Aalto settings must describe five coils, optionally a zero sixth channel')
        if not isinstance(voltages, list) or not isinstance(polarities, list) or len(voltages) != len(rows) or len(polarities) != len(rows):
            raise ConversionError('Channel rows, voltage list and polarity list must have matching lengths')
        original, scaled = target.get('original_weights'), target.get('scaled_weights')
        if not isinstance(original, list) or not isinstance(scaled, list) or len(original) != 5 or len(scaled) != 5:
            raise ConversionError('Expected five original and scaled optimization weights')
        charge = [0.0] * 6
        pulse_commands, ids, weight_ids, basis_ids, calibration_ids = [], set(), set(), set(), set()
        for row in rows:
            channel = integer(row.get('device_channel'), 'device_channel')
            if channel >= len(rows) or channel in ids:
                raise ConversionError('Duplicate or out-of-range device channel')
            ids.add(channel)
            voltage = number(row.get('target_voltage_v'), 'target_voltage_v')
            reverse = boolean(row.get('reverse_polarity'), 'reverse_polarity')
            close(voltages[channel], voltage, 'voltage list')
            if boolean(polarities[channel], 'polarity list') != reverse:
                raise ConversionError('Polarity list disagrees with channel row')
            if voltage < 0:
                raise ConversionError('Charge voltage must be nonnegative')
            if channel == 5:
                if voltage != 0 or reverse or number(row.get('signed_load_voltage_v'), 'sixth signed voltage') != 0:
                    raise ConversionError('Unused sixth Aalto channel must be zero with reverse_polarity=false')
                for field in ('model_didt_a_per_s', 'device_didt_a_per_s', 'weight'):
                    if field in row and number(row[field], 'sixth ' + field) != 0:
                        raise ConversionError('Unused sixth channel must not contain nonzero currents or weights')
                continue
            entry = by_device[channel]
            limit = min(1490.0, number(entry['max_voltage_v'], 'configured voltage limit', positive=True),
                        number(row.get('max_voltage_v'), 'settings voltage limit', positive=True))
            if voltage > limit:
                raise ConversionError(f'Target {index}, channel {channel}: {voltage:g} V exceeds {limit:g} V')
            signed = number(row.get('signed_load_voltage_v'), 'signed_load_voltage_v')
            close(voltage, abs(signed), 'absolute voltage')
            if reverse != (signed < 0):
                raise ConversionError('Reverse polarity disagrees with signed voltage')
            weight_index = integer(row.get('weight_index'), 'weight_index')
            basis_index = integer(row.get('basis_channel_index'), 'basis_channel_index')
            coil_number = integer(row.get('calibration_coil_number'), 'calibration_coil_number', minimum=1)
            if weight_index not in range(5) or weight_index in weight_ids or basis_index not in range(5) or basis_index in basis_ids or coil_number in calibration_ids:
                raise ConversionError('Weights, basis channels and calibration coils must each be unique')
            weight_ids.add(weight_index); basis_ids.add(basis_index); calibration_ids.add(coil_number)
            if basis_index != entry.get('basis_channel_index') or coil_number != entry.get('calibration_coil_number'):
                raise ConversionError('Channel mapping disagrees with configuration')
            correction = number(row.get('polarity_correction'), 'polarity_correction')
            expected = profiles[profile][basis_index] if profiles is not None else entry.get('polarity')
            if correction not in (-1, 1) or correction != expected:
                raise ConversionError('Polarity correction disagrees with configuration')
            weight = number(row.get('weight'), 'weight')
            close(original[weight_index], weight, 'original weight')
            close(scaled[weight_index], weight * scale, 'scaled weight')
            basis = number(row.get('basis_didt'), 'basis_didt')
            if basis == 0:
                raise ConversionError('Basis dI/dt must be nonzero')
            model_didt = weight * basis * scale * (1 if unit == 'A/s' else 1e6)
            close(row.get('model_didt_a_per_s'), model_didt, 'model dI/dt')
            close(row.get('device_didt_a_per_s'), model_didt * correction, 'device dI/dt')
            coefficient = number(row.get('volts_per_didt'), 'volts_per_didt', positive=True)
            close(signed, model_didt * correction * coefficient, 'calibrated voltage arithmetic')
            charge[channel] = voltage
            pulse_commands.append({'method': 'send_pulse', 'channel': channel,
                'execution_condition': 'WAIT_FOR_TRIGGER', 'reverse_polarity': reverse,
                'waveform_reference': {'phases': reference['phases'], 'durations_in_ticks': [rise, hold, falls[channel]]}})
        if ids != set(range(len(rows))):
            raise ConversionError('Channel IDs must cover every position in the output lists')
        score = target.get('source_score')
        if score is not None and number(score, 'source_score') < 0:
            raise ConversionError('source_score must be nonnegative')
        achieved = target.get('source_achieved_fields')
        if achieved is not None:
            if not isinstance(achieved, list) or len(achieved) != 3:
                raise ConversionError('Expected a three-component achieved target field')
            for value in achieved:
                number(value, 'source_achieved_fields')
        plans.append({'target_index': index, 'label': target.get('label'),
            'source_score': target.get('source_score'), 'source_achieved_fields': target.get('source_achieved_fields'),
            'charge_preview': {'method': 'send_immediate_charge_or_discharge_to_all_channels', 'target_voltages': charge},
            'pulse_previews': sorted(pulse_commands, key=lambda c: c['channel']),
            'sixth_channel': {'device_channel': 5, 'target_voltage_v': 0.0, 'pulse_scheduled': False}})
    if selected is not None and selected - seen:
        raise ConversionError(f'Missing selected targets {sorted(selected - seen)}')
    if not plans:
        raise ConversionError('No selected targets')
    return {'schema': 'mtms.targeting_trial_preview.v1', 'dry_run_only': True, 'device_connected': False,
        'commands_executed': False, 'stimulation_performed': False, 'settings_checks': 'passed',
        'physical_field_validation': 'not performed', 'calibration_measurement_validation': 'not performed',
        'hardware_ready': False, 'waveform_id': waveform, 'targets': plans}


def render(report):
    lines = ['DRY RUN ONLY — settings checks passed; physical E-field NOT validated.',
             'No API imported, no connection, no commands executed. Each target is an independent trial preview.',
             'Channel numbers below are zero-based. The plan sets channel 5 to 0 V and schedules NO pulse for it.']
    for target in report['targets']:
        lines += ['', f"Target {target['target_index'] + 1} (index {target['target_index']}): {target['label']}",
                  f"Source relative error: {target['source_score']}; achieved vector: {target['source_achieved_fields']}",
                  '# Proposed charge/discharge request; not executed:',
                  'api.send_immediate_charge_or_discharge_to_all_channels(target_voltages=' + repr(target['charge_preview']['target_voltages']) + ')']
        for command in target['pulse_previews']:
            channel = command['channel']
            lines += [f"# Channel {channel}: reference phase durations {command['waveform_reference']['durations_in_ticks']} ticks",
                      f"api.send_pulse(channel={channel}, waveform=<verified reference waveform>, execution_condition=ExecutionCondition.WAIT_FOR_TRIGGER, reverse_polarity={command['reverse_polarity']})"]
    lines += ['', 'Preview omits session setup, charge completion checks, triggers, and acquisition; it is not an executable stimulation protocol.']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('settings', type=Path)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--target-index', type=int, action='append')
    parser.add_argument('--output', type=Path, help='Optional inert JSON preview (must not exist)')
    args = parser.parse_args(argv)
    try:
        settings = load_json(args.settings)
        config = load_json(args.config)
        original_config_hash = settings.get('sources', {}).get('conversion_config', {}).get('sha256')
        if original_config_hash is not None and original_config_hash != hashlib.sha256(args.config.read_bytes()).hexdigest():
            raise ConversionError('Configuration has changed since conversion; regenerate settings with this config')
        report = preview_settings(settings, config, args.target_index)
        report['sources'] = {name: {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                             for name, path in [('settings', args.settings), ('config', args.config)]}
        if args.output:
            if args.output.resolve() in (args.settings.resolve(), args.config.resolve()):
                raise ConversionError('Output must not overwrite input files')
            with args.output.open('x', encoding='utf-8') as stream:
                json.dump(report, stream, indent=2, allow_nan=False)
                stream.write('\n')
        print(render(report))
        return 0
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        print(f'Dry-run validation failed: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
