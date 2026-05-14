#include "imu_drv.h"

#include "app_error.h"
#include "nrf_drv_twi.h"

#define MPU6050_ADDR            0x68
#define MPU6050_REG_WHO_AM_I    0x75
#define MPU6050_REG_PWR_MGMT_1  0x6B
#define MPU6050_REG_GYRO_CFG    0x1B
#define MPU6050_REG_GYRO_XOUT_H 0x43

#define MPU6050_EXPECTED_WHOAMI 0x68

#define IMU_TWI_INSTANCE_ID     0
#define IMU_PIN_SCL             3   // P0.03
#define IMU_PIN_SDA             4   // P0.04

static const nrf_drv_twi_t m_twi = NRF_DRV_TWI_INSTANCE(IMU_TWI_INSTANCE_ID);
static bool m_twi_inited = false;

static bool mpu6050_write_u8(uint8_t reg, uint8_t value)
{
    uint8_t data[2] = { reg, value };
    return (nrf_drv_twi_tx(&m_twi, MPU6050_ADDR, data, sizeof(data), false) == NRF_SUCCESS);
}

static bool mpu6050_read(uint8_t reg, uint8_t * p_buf, uint8_t len)
{
    ret_code_t ret;

    ret = nrf_drv_twi_tx(&m_twi, MPU6050_ADDR, &reg, 1, true);
    if (ret != NRF_SUCCESS)
    {
        return false;
    }

    ret = nrf_drv_twi_rx(&m_twi, MPU6050_ADDR, p_buf, len);
    return (ret == NRF_SUCCESS);
}

bool imu_drv_init(void)
{
    ret_code_t ret;
    nrf_drv_twi_config_t const twi_config = {
        .scl                = IMU_PIN_SCL,
        .sda                = IMU_PIN_SDA,
        .frequency          = NRF_DRV_TWI_FREQ_400K,
        .interrupt_priority = APP_IRQ_PRIORITY_LOW,
        .clear_bus_init     = false
    };

    if (!m_twi_inited)
    {
        ret = nrf_drv_twi_init(&m_twi, &twi_config, NULL, NULL);
        if (ret != NRF_SUCCESS)
        {
            return false;
        }

        nrf_drv_twi_enable(&m_twi);
        m_twi_inited = true;
    }

    uint8_t whoami = 0;
    if (!mpu6050_read(MPU6050_REG_WHO_AM_I, &whoami, 1))
    {
        return false;
    }
    if (whoami != MPU6050_EXPECTED_WHOAMI)
    {
        return false;
    }

    // Wake up device.
    if (!mpu6050_write_u8(MPU6050_REG_PWR_MGMT_1, 0x00))
    {
        return false;
    }

    // Gyro full-scale = ±2000 dps (16.4 LSB/(deg/s)).
    if (!mpu6050_write_u8(MPU6050_REG_GYRO_CFG, 0x18))
    {
        return false;
    }

    return true;
}

bool imu_drv_read_gyro(imu_gyro_sample_t * sample)
{
    uint8_t raw[6];

    if ((sample == NULL) || !mpu6050_read(MPU6050_REG_GYRO_XOUT_H, raw, sizeof(raw)))
    {
        return false;
    }

    int16_t gx = (int16_t)((raw[0] << 8) | raw[1]);
    int16_t gy = (int16_t)((raw[2] << 8) | raw[3]);
    int16_t gz = (int16_t)((raw[4] << 8) | raw[5]);

    // ±2000 dps scale factor.
    sample->gx_dps = ((float)gx) / 16.4f;
    sample->gy_dps = ((float)gy) / 16.4f;
    sample->gz_dps = ((float)gz) / 16.4f;

    return true;
}
