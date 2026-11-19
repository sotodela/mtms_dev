import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from convert_targeting_weights import convert_export, ConversionError
from dry_run_targeting_trial import main, preview_settings, render


class DryRunTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[3]
        self.config = json.loads((root / 'conversion_config.json').read_text())
        pose = {'position': [0, 0, 0], 'orientation': [0, 0, 0]}
        export = {'schema': 'mtms.efield_targeting_results.v1', 'basis_dIperdt': [1]*5,
                  'inputs': {'coil_model_path': 'coilset-5-v230908.bin'},
                  'channels': [{'channel_index': i, 'weight_index': i, 'coil_position': pose} for i in range(5)],
                  'results': [{'kind': 'target_optimization', 'target_index': 0,
                               'weights': [1e6, -2e6, 0, 3e6, -4e6], 'score': .01, 'achieved_fields': [1, 0, 0]}]}
        self.settings = convert_export(export, self.config, [2e-5]*5, 1)

    def preview(self, **kwargs):
        return preview_settings(self.settings, self.config, **kwargs)

    def test_preview_six_charge_channels_but_only_five_pulses(self):
        before = deepcopy(self.settings)
        report = self.preview()
        target = report['targets'][0]
        for actual, expected in zip(target['charge_preview']['target_voltages'], [20, 40, 0, 60, 80, 0]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual([c['channel'] for c in target['pulse_previews']], list(range(5)))
        self.assertEqual([c['reverse_polarity'] for c in target['pulse_previews']], [False, False, False, True, False])
        self.assertFalse(target['sixth_channel']['pulse_scheduled'])
        self.assertFalse(report['hardware_ready'])
        self.assertEqual(report['physical_field_validation'], 'not performed')
        self.assertEqual(before, self.settings)
        self.assertIn('physical E-field NOT validated', render(report))

    def test_explicit_zero_sixth_channel_and_nonzero_rejection(self):
        target = self.settings['targets'][0]
        target['channels'].append({'device_channel': 5, 'target_voltage_v': 0, 'signed_load_voltage_v': 0, 'reverse_polarity': False})
        target['target_voltages'].append(0)
        target['reverse_polarities'].append(False)
        self.preview()
        target['channels'][-1]['target_voltage_v'] = 1
        target['target_voltages'][-1] = 1
        with self.assertRaisesRegex(ConversionError, 'sixth'):
            self.preview()

    def test_invalid_limits_mapping_arithmetic_and_flags(self):
        mutations = [
            lambda: self.config['channels'][0].update(max_voltage_v=1),
            lambda: self.settings['targets'][0]['channels'][0].update(device_channel=1),
            lambda: self.settings['targets'][0]['target_voltages'].__setitem__(0, 200),
            lambda: self.settings['targets'][0]['channels'][0].update(reverse_polarity='false'),
            lambda: self.settings['targets'][0]['channels'][0].update(volts_per_didt=3e-5),
            lambda: self.settings['targets'][0]['channels'][0].update(model_didt_a_per_s=2e6),
            lambda: self.settings['targets'][0]['channels'][0].update(calibration_coil_number=2),
            lambda: self.settings.update(waveform_id='wrong'),
            lambda: self.settings.update(weight_scale=float('nan')),
            lambda: self.config['waveform_reference'].update(falling_ticks_by_device_channel=[10]*6),
        ]
        for mutation in mutations:
            self.setUp()
            mutation()
            with self.subTest(mutation=mutation), self.assertRaises(ConversionError):
                self.preview()

    def test_multiple_targets_selection_and_duplicate_rejection(self):
        second = deepcopy(self.settings['targets'][0]); second['target_index'] = 2
        self.settings['targets'].append(second)
        self.assertEqual([t['target_index'] for t in self.preview()['targets']], [0, 2])
        self.assertEqual([t['target_index'] for t in self.preview(target_indices=[2])['targets']], [2])
        with self.assertRaises(ConversionError): self.preview(target_indices=[9])
        second['target_index'] = 0
        with self.assertRaises(ConversionError): self.preview()

    def test_cli_no_hardware_imports_and_no_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); settings = root/'settings.json'; config = root/'config.json'; output = root/'preview.json'
            settings.write_text(json.dumps(self.settings)); config.write_text(json.dumps(self.config))
            arguments = [str(settings), '--config', str(config), '--output', str(output)]
            import builtins
            original_import = builtins.__import__
            def guard(name, *args, **kwargs):
                if name.startswith(('rclpy', 'MTMSApi', 'scipy')):
                    raise AssertionError('Dry run attempted a device/scientific dependency import')
                return original_import(name, *args, **kwargs)
            with patch('builtins.__import__', guard), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(arguments), 0)
                self.assertFalse(json.loads(output.read_text())['commands_executed'])
                self.assertEqual(main(arguments), 2)  # never overwrite a previous preview
                arguments[-1] = str(root/'invalid.json')
                self.settings['targets'][0]['target_voltages'][0] = float('inf')
                settings.write_text(json.dumps(self.settings))
                self.assertEqual(main(arguments), 2)
                self.assertFalse((root/'invalid.json').exists())


if __name__ == '__main__':
    unittest.main()
