import contextlib
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from convert_targeting_weights import ConversionError, convert_export, load_calibration, main


class ConversionTests(unittest.TestCase):
    def setUp(self):
        pose = {'position': [1, 2, 3], 'orientation': [0, 0, 0], 'coordinate_frame': 'invesalius'}
        self.export = {'optimization': {
            'schema': 'mtms.efield_targeting_results.v1', 'basis_dIperdt': [1, 2],
            'channels': [{'channel_index': i, 'weight_index': i, 'coil_position': deepcopy(pose)} for i in range(2)],
            'inputs': {'target_points': [{'world_position': [4, 5, 6]}]},
            'results': [
                {'kind': 'channel_reference', 'weights': [1, 0]},
                {'kind': 'target_optimization', 'target_index': 0, 'weights': [2, -3], 'label': 'T1'},
                {'kind': 'target_optimization', 'target_index': 1, 'weights': [0, 1], 'label': 'T2'}]}}
        self.config = {'schema': 'mtms.weight_conversion_config.v1', 'basis_didt_unit': 'A/s',
                       'waveform_id': 'synthetic_test_waveform', 'channels': [
                           {'basis_channel_index': i, 'device_channel': i, 'calibration_coil_number': i+1,
                            'polarity': 1, 'max_voltage_v': 1000} for i in range(2)]}
        self.coefficients = [2e-5, 3e-5]

    def convert(self, **kwargs):
        return convert_export(self.export, self.config, self.coefficients, 1e6, **kwargs)

    def test_signed_conversion_and_targets(self):
        before = deepcopy(self.export)
        result = self.convert()
        self.assertEqual(len(result['targets']), 2)
        first = result['targets'][0]
        self.assertAlmostEqual(first['target_voltages'][0], 40)
        self.assertAlmostEqual(first['target_voltages'][1], 180)
        self.assertEqual(first['reverse_polarities'], [False, True])
        self.assertEqual(first['target']['world_position'], [4, 5, 6])
        self.assertEqual(result['targets'][1]['target_voltages'][0], 0)
        self.assertEqual(self.export, before)
        self.assertFalse(result['stimulation_performed'])

    def test_mapping_polarity_and_weight_order(self):
        self.config['channels'][0].update(device_channel=1, calibration_coil_number=2, polarity=-1)
        self.config['channels'][1].update(device_channel=0, calibration_coil_number=1)
        self.export['optimization']['channels'][0]['weight_index'] = 1
        self.export['optimization']['channels'][1]['weight_index'] = 0
        first = self.convert()['targets'][0]
        self.assertAlmostEqual(first['target_voltages'][0], 80)
        self.assertAlmostEqual(first['target_voltages'][1], 90)
        self.assertEqual(first['reverse_polarities'], [False, False])

    def test_microsecond_units(self):
        self.config['basis_didt_unit'] = 'A/us'
        report = convert_export(self.export, self.config, self.coefficients, 1)
        expected = self.convert_with_a_per_s()
        for actual, target in zip(report['targets'], expected['targets']):
            self.assertEqual(actual['target_voltages'], target['target_voltages'])
            self.assertEqual(actual['channels'], target['channels'])

    def convert_with_a_per_s(self):
        self.config['basis_didt_unit'] = 'A/s'
        return self.convert()

    def test_model_specific_polarity(self):
        self.config['polarity_by_coil_model'] = {'coilset_5_v230908': [1, -1], 'coilset_5_v251022': [1, 1]}
        self.export['optimization']['inputs']['coil_model_path'] = '/models/coilset_5_v230908.ccd'
        report = self.convert()
        self.assertEqual(report['polarity_profile'], 'coilset_5_v230908')
        self.assertEqual(report['targets'][0]['reverse_polarities'], [False, False])
        self.export['optimization']['inputs']['coil_model_path'] = '/models/coilset-5-v230908.bin'
        self.assertEqual(self.convert()['polarity_profile'], 'coilset_5_v230908')
        self.export['optimization']['inputs']['coil_model_path'] = '/models/coilset_5_v251022.ccd'
        self.assertEqual(self.convert()['targets'][0]['reverse_polarities'], [False, True])
        for path in ('', '/models/unknown.ccd', '/models/coilset_5_v230908_modified.ccd'):
            self.export['optimization']['inputs']['coil_model_path'] = path
            with self.assertRaises(ConversionError):
                self.convert()

    def test_selection(self):
        self.assertEqual([x['target_index'] for x in self.convert(target_indices=[1])['targets']], [1])
        for selection in ([9], [-1]):
            with self.assertRaises(ConversionError):
                self.convert(target_indices=selection)

    def test_invalid_inputs(self):
        mutations = [
            lambda: self.config.pop('basis_didt_unit'),
            lambda: self.config['channels'][0].update(max_voltage_v=1),
            lambda: self.config['channels'][0].update(polarity=0),
            lambda: self.config['channels'][0].update(device_channel=1),
            lambda: self.config['channels'][0].update(calibration_coil_number=9),
            lambda: self.export['optimization']['channels'][1].update(channel_index=0),
            lambda: self.export['optimization']['channels'][1]['coil_position'].update(position=[9, 9, 9]),
            lambda: self.export['optimization']['results'][2].update(target_index=0),
            lambda: self.export['optimization']['results'][1].update(weights=[float('nan'), 1]),
            lambda: self.coefficients.__setitem__(0, 0),
        ]
        for mutate in mutations:
            self.setUp()
            mutate()
            with self.subTest(mutation=mutate), self.assertRaises(ConversionError):
                self.convert()

    def test_cli_json_and_no_input_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export, config, calibration, output = [root / name for name in ('export.json', 'config.json', 'calibration.json', 'out.json')]
            export.write_text(json.dumps(self.export))
            calibration.write_text(json.dumps({'didt_unit': 'A/s', 'volts_per_didt': self.coefficients}))
            self.config['calibration_file'] = calibration.name
            config.write_text(json.dumps(self.config))
            args = [str(export), '--config', str(config), '--scale', '1000000', '--output', str(output)]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 2)
                report = json.loads(output.read_text())
                self.assertEqual(len(report['sources']['calibration']['sha256']), 64)
                args[-1] = str(export)
                self.assertEqual(main(args + ['--overwrite']), 2)
                self.assertEqual(json.loads(export.read_text()), self.export)
                args[-1] = str(root / 'failed.json')
                self.config['channels'][0]['max_voltage_v'] = 1
                config.write_text(json.dumps(self.config))
                self.assertEqual(main(args), 2)
                self.assertFalse((root / 'failed.json').exists())

    @unittest.skipUnless(importlib.util.find_spec('scipy'), 'SciPy optional')
    def test_bundled_aalto_calibration_matches_actual_mat_file(self):
        import hashlib
        root = Path(__file__).resolve().parents[3]
        original = root/'src/waveform_approximator/waveform_approximator/data/aalto_mk3/calibration.mat'
        bundled = root/'src/neuronavigation/invesalius3/plugins/efield_targeting_area/calibration/aalto_mk3.json'
        self.assertEqual(load_calibration(original), load_calibration(bundled))
        self.assertEqual(json.loads(bundled.read_text())['source_calibration_sha256'], hashlib.sha256(original.read_bytes()).hexdigest())

    @unittest.skipUnless(importlib.util.find_spec('scipy'), 'SciPy optional')
    def test_mat_calibration(self):
        from scipy.io import savemat
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calibration.mat'
            for values in (self.coefficients, [2e-5]):
                savemat(path, {'calibration_data': {'volts_per_didt': values}})
                self.assertEqual(load_calibration(path), values)
            savemat(path, {'calibration_data': {'volts_per_didt': []}})
            with self.assertRaises(ConversionError):
                load_calibration(path)


if __name__ == '__main__':
    unittest.main()
