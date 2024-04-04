from __future__ import annotations
import math
import cffirmware

class EstimatorKalmanEmulator:
    """
    This class emulates the behavior of estimator_kalman.c and is used as a helper to enable testing of the kalman
    core functionatlity. Estimator_kalman.c is tightly coupled to FreeRTOS (using
    tasks for instance) and can not really be tested on this level, instead this class can be used to drive the
    kalman core functionality.

    The class emulates the measurement queue, the main loop in the task and the various calls to kalman core.

    Methods are named in a similar way to the functions in estimator_kalman.c to make it easier to understand
    how they are connected.

    """
    def __init__(self, anchor_positions=None, basestation_poses=None, basestation_calibration=None) -> None:
        self.anchor_positions = anchor_positions
        self.basestation_poses = basestation_poses
        self.basestation_calibration = basestation_calibration
        self.accSubSampler = cffirmware.Axis3fSubSampler_t()
        self.gyroSubSampler = cffirmware.Axis3fSubSampler_t()
        self.coreData = cffirmware.kalmanCoreData_t()
        self.outlierFilterStateTdoa = cffirmware.OutlierFilterTdoaState_t()
        self.outlierFilterStateLH = cffirmware.OutlierFilterLhState_t()

        self.TDOA_ENGINE_MEASUREMENT_NOISE_STD = 0.30
        self.LH_ENGINE_MEASUREMENT_NOISE_STD = 0.001
        self.PREDICT_RATE = 100
        self.PREDICT_STEP_MS = 1000 / self.PREDICT_RATE

        self._is_initialized = False

    def run_one_1khz_iteration(self, sensor_samples) -> tuple[float, cffirmware.state_t]:
        """
        Run one iteration of the estimation loop (runs at 1kHz)

        Args:
            sensor_samples : a list of samples to be consumed. The samples with time stamps that are used in this
                             iteration will be popped from the list.

        Returns:
            tuple[float, cffirmware.state_t]: A tuple containing the time stamp of this iteration and the
                                              estimated state
        """
        if not self._is_initialized:
            first_sample = sensor_samples[0]
            time_ms = int(first_sample[1]['timestamp'])
            self._lazy_init(time_ms)

        # Simplification, assume always flying
        quad_is_flying = True

        if self.now_ms > self.next_prediction_ms:
            cffirmware.axis3fSubSamplerFinalize(self.accSubSampler)
            cffirmware.axis3fSubSamplerFinalize(self.gyroSubSampler)

            cffirmware.kalmanCorePredict(self.coreData, self.accSubSampler.subSample, self.gyroSubSampler.subSample,
                                            self.now_ms, quad_is_flying)

            self.next_prediction_ms += self.PREDICT_STEP_MS

        cffirmware.kalmanCoreAddProcessNoise(self.coreData, self.coreParams, self.now_ms)

        self._update_queued_measurements(self.now_ms, sensor_samples)

        cffirmware.kalmanCoreFinalize(self.coreData)

        # Main loop called at 1000 Hz in the firmware
        self.now_ms += 1

        external_state = cffirmware.state_t()
        acc_latest = cffirmware.Axis3f()
        cffirmware.kalmanCoreExternalizeState(self.coreData, external_state, acc_latest)

        return self.now_ms, external_state

    def _lazy_init(self, sample_time_ms):
        self.now_ms = sample_time_ms
        self.next_prediction_ms = self.now_ms + self.PREDICT_STEP_MS

        GRAVITY_MAGNITUDE = 9.81
        DEG_TO_RAD = math.pi / 180.0
        cffirmware.axis3fSubSamplerInit(self.accSubSampler, GRAVITY_MAGNITUDE)
        cffirmware.axis3fSubSamplerInit(self.gyroSubSampler, DEG_TO_RAD)

        self.coreParams = cffirmware.kalmanCoreParams_t()
        cffirmware.kalmanCoreDefaultParams(self.coreParams)
        cffirmware.outlierFilterTdoaReset(self.outlierFilterStateTdoa)
        cffirmware.outlierFilterLighthouseReset(self.outlierFilterStateLH, self.now_ms)
        cffirmware.kalmanCoreInit(self.coreData, self.coreParams, self.now_ms)

        self._is_initialized = True

    def _update_queued_measurements(self, now_ms: int, sensor_samples):
        done = False

        while len(sensor_samples):
            sample = sensor_samples.pop(0)
            time_ms = int(sample[1]['timestamp'])
            if time_ms <= now_ms:
                self._update_with_sample(sample, now_ms)
            else:
                return

    def _update_with_sample(self, sample, now_ms):
        position = [0.0, 0.0, 0.0]
        position[0] = cffirmware.get_state(self.coreData, 0)
        position[1] = cffirmware.get_state(self.coreData, 1)
        position[2] = cffirmware.get_state(self.coreData, 2)
        #print("Position: ", position)

        rotation_matrix = [[0.0, 0.0, 0.0],[0.0, 0.0, 0.0],[0.0, 0.0, 0.0]]

        for i in range(0, 3):
            for j in range(0, 3):
                rotation_matrix[i][j] = cffirmware.get_mat_index(self.coreData, i,j)

        #print("Position: ", position)
        #print("Rotation Matrix: ", rotation_matrix)

        if sample[0] == 'estTDOA':
            tdoa_data = sample[1]
            tdoa = cffirmware.tdoaMeasurement_t()

            tdoa.anchorIdA = int(tdoa_data['idA'])
            tdoa.anchorIdB = int(tdoa_data['idB'])
            tdoa.anchorPositionA = self.anchor_positions[tdoa.anchorIdA]
            tdoa.anchorPositionB = self.anchor_positions[tdoa.anchorIdB]
            tdoa.distanceDiff = float(tdoa_data['distanceDiff'])
            tdoa.stdDev = self.TDOA_ENGINE_MEASUREMENT_NOISE_STD

            cffirmware.kalmanCoreUpdateWithTdoa(self.coreData, tdoa, now_ms, self.outlierFilterStateTdoa)

        if sample[0] == 'estYawError':
            yaw_error_data  = sample[1]
            yaw_error = cffirmware.yawErrorMeasurement_t()
            yaw_error.yawError = float(yaw_error_data['yawError'])
            yaw_error.stdDev = 0.01

            cffirmware.kalmanCoreUpdateWithYawError(self.coreData, yaw_error)


        if sample[0] == 'estSweepAngle':
            sweep_data = sample[1]
            sweep = cffirmware.sweepAngleMeasurement_t()

            sweep.sensorId = int(sweep_data['sensorId'])
            sweep.baseStationId = int(sweep_data['baseStationId'])
            sweep.sweepId = int(sweep_data['sweepId'])
            sweep.t = float(sweep_data['t'])
            sweep.measuredSweepAngle = float(sweep_data['sweepAngle'])
            sweep.stdDev = self.LH_ENGINE_MEASUREMENT_NOISE_STD
            cffirmware.set_calibration_model(sweep, self.basestation_calibration[sweep.baseStationId][sweep.sweepId])

            sensor_pos_w = 0.015/2.0
            sensor_pos_l = 0.030/2.0
            sensor_position = {}
            sensor_position[0] = [-sensor_pos_w, sensor_pos_l, 0.0]
            sensor_position[1] = [-sensor_pos_w, -sensor_pos_l, 0.0]
            sensor_position[2] = [sensor_pos_w, sensor_pos_l, 0.0]
            sensor_position[3] = [sensor_pos_w, -sensor_pos_l, 0.0]

            sensorPos = cffirmware.vec3_s()
            sensorPos.x = sensor_position[int(sweep.sensorId)][0]
            sensorPos.y = sensor_position[int(sweep.sensorId)][1]
            sensorPos.z = sensor_position[int(sweep.sensorId)][2]

            rotorPos = cffirmware.vec3_s()
            rotorPos.x = self.basestation_poses[sweep.baseStationId]['origin'].x
            rotorPos.y = self.basestation_poses[sweep.baseStationId]['origin'].y
            rotorPos.z = self.basestation_poses[sweep.baseStationId]['origin'].z
            print(rotorPos.x, rotorPos.y, rotorPos.z)

            rotorRot = cffirmware.mat3_s()
            rotorRot.i11 = self.basestation_poses[sweep.baseStationId]['mat'].i11
            rotorRot.i12 = self.basestation_poses[sweep.baseStationId]['mat'].i12
            rotorRot.i13 = self.basestation_poses[sweep.baseStationId]['mat'].i13
            rotorRot.i21 = self.basestation_poses[sweep.baseStationId]['mat'].i21
            rotorRot.i22 = self.basestation_poses[sweep.baseStationId]['mat'].i22
            rotorRot.i23 = self.basestation_poses[sweep.baseStationId]['mat'].i23
            rotorRot.i31 = self.basestation_poses[sweep.baseStationId]['mat'].i31
            rotorRot.i32 = self.basestation_poses[sweep.baseStationId]['mat'].i32
            rotorRot.i33 = self.basestation_poses[sweep.baseStationId]['mat'].i33

            # transpose of the rotation matrix
            rotorRotInv = cffirmware.mat3_s()
            rotorRotInv.i11 = self.basestation_poses[sweep.baseStationId]['mat'].i11
            rotorRotInv.i12 = self.basestation_poses[sweep.baseStationId]['mat'].i21
            rotorRotInv.i13 = self.basestation_poses[sweep.baseStationId]['mat'].i31
            rotorRotInv.i21 = self.basestation_poses[sweep.baseStationId]['mat'].i12
            rotorRotInv.i22 = self.basestation_poses[sweep.baseStationId]['mat'].i22
            rotorRotInv.i23 = self.basestation_poses[sweep.baseStationId]['mat'].i32
            rotorRotInv.i31 = self.basestation_poses[sweep.baseStationId]['mat'].i13
            rotorRotInv.i32 = self.basestation_poses[sweep.baseStationId]['mat'].i23
            rotorRotInv.i33 = self.basestation_poses[sweep.baseStationId]['mat'].i33



            sweep.sensorPos = sensorPos
            sweep.rotorPos = rotorPos
            sweep.rotorRot = rotorRot
            sweep.rotorRotInv = rotorRotInv

            cffirmware.kalmanCoreUpdateWithSweepAngles(self.coreData, sweep, now_ms, self.outlierFilterStateLH)




        if sample[0] == 'estAcceleration':
            acc_data = sample[1]

            acc = cffirmware.Axis3f()
            acc.x = float(acc_data['acc.x'])
            acc.y = float(acc_data['acc.y'])
            acc.z = float(acc_data['acc.z'])

            cffirmware.axis3fSubSamplerAccumulate(self.accSubSampler, acc)

        if sample[0] == 'estGyroscope':
            gyro_data = sample[1]

            gyro = cffirmware.Axis3f()
            gyro.x = float(gyro_data['gyro.x'])
            gyro.y = float(gyro_data['gyro.y'])
            gyro.z = float(gyro_data['gyro.z'])

            cffirmware.axis3fSubSamplerAccumulate(self.gyroSubSampler, gyro)
