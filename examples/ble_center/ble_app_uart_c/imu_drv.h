#ifndef IMU_DRV_H
#define IMU_DRV_H

#include <stdbool.h>
#include <stdint.h>

typedef struct
{
    float gx_dps;
    float gy_dps;
    float gz_dps;
} imu_gyro_sample_t;

bool imu_drv_init(void);
bool imu_drv_read_gyro(imu_gyro_sample_t * sample);

#endif
