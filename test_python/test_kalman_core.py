#!/usr/bin/env python

import numpy as np
from bindings.util.estimator_kalman_emulator import EstimatorKalmanEmulator
from bindings.util.sd_card_file_runner import SdCardFileRunner
from bindings.util.loco_utils import read_loco_anchor_positions
from bindings.util.lighthouse_utils import read_lh_basestation_pose_calibration

def test_kalman_core_with_tdoa3():
    # Fixture
    fixture_base = 'test_python/fixtures/kalman_core'
    anchor_positions = read_loco_anchor_positions(fixture_base + '/anchor_positions.yaml')
    runner = SdCardFileRunner(fixture_base + '/log05')
    emulator = EstimatorKalmanEmulator(anchor_positions=anchor_positions)

    # Test
    actual = runner.run_estimator_loop(emulator)

    # Assert
    # Verify that the final position is close-ish to (0, 0, 0)
    actual_final_pos = np.array(actual[-1][1])
    assert np.linalg.norm(actual_final_pos - [0.0, 0.0, 0.0]) < 0.4


def test_kalman_core_with_sweep_angles():

    # Fixture
    fixture_base = 'test_python/fixtures/kalman_core'
    bs_calib, bs_geo = read_lh_basestation_pose_calibration(fixture_base + '/geometry.yaml')
    runner = SdCardFileRunner(fixture_base + '/Bindings13')
    emulator = EstimatorKalmanEmulator(basestation_calibration=bs_calib, basestation_poses=bs_geo)

    # Test
    actual = runner.run_estimator_loop(emulator)

    # Assert
    # Verify that the final position is close-ish to (0, 0, 0)

    #for it in range(1,len(np.array(actual[:])),100):
    #    print(actual[it][1])
    actual_final_pos = np.array(actual[-1][1])
    #print(actual_final_pos)
    assert np.linalg.norm(actual_final_pos - [0.8, -1.2, 0.5]) < 0.4