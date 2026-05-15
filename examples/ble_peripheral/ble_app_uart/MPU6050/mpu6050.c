#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>

#include "nrf_drv_twi.h"
#include "mpu6050.h"

extern void ble_send(uint8_t * string, uint16_t length);

#define TWI_INSTANCE_ID                  0
#define GYRO_DEADZONE_DPS                1.2f
#define GYRO_TO_MOUSE_GAIN               0.18f
#define GYRO_SENSITIVITY_LSB_PER_DPS     16.4f
#define TWI_XFER_TIMEOUT_LOOPS           20000U

static volatile bool m_xfer_done = false;
static const nrf_drv_twi_t m_twi = NRF_DRV_TWI_INSTANCE(TWI_INSTANCE_ID);
static mpu_mouse_transport_cb_t m_mouse_transport_cb = NULL;

static mpu_mouse_profile_t m_mouse_profile = MPU_MOUSE_PROFILE_BALANCED;

static void mouse_report_send_transport(int8_t dx, int8_t dy)
{
    if (m_mouse_transport_cb != NULL)
    {
        m_mouse_transport_cb(dx, dy);
        return;
    }

#if MOUSE_SEND_TRANSPORT_NUS
    char mouse_report[32];
    uint16_t send_len = (uint16_t)snprintf(mouse_report, sizeof(mouse_report), "M,%d,%d\n", dx, dy);
    if (send_len > 0)
    {
        ble_send((uint8_t *)mouse_report, send_len);
    }
#else
    // MANUAL_EDIT_POINT: ??HID????,?????? ble_hids_inp_rep_send(...)
    (void)dx;
    (void)dy;
#endif
}


void mpu6050_set_mouse_transport(mpu_mouse_transport_cb_t cb)
{
    m_mouse_transport_cb = cb;
}


void mpu6050_set_mouse_profile(mpu_mouse_profile_t profile)
{
    m_mouse_profile = profile;
}
static int8_t clamp_i8(int32_t value)
{
    if (value > 127)
    {
        return 127;
    }
    if (value < -127)
    {
        return -127;
    }
    return (int8_t)value;
}

static bool twi_wait_done_with_timeout(void)
{
    uint32_t timeout = TWI_XFER_TIMEOUT_LOOPS;
    while ((m_xfer_done == false) && (timeout > 0U))
    {
        timeout--;
    }

    return (timeout > 0U);
}

void twi_handler(nrf_drv_twi_evt_t const * p_event, void * p_context)
{
    (void)p_context;

    switch (p_event->type)
    {
        case NRF_DRV_TWI_EVT_DONE:
            m_xfer_done = true;
            break;

        case NRF_DRV_TWI_EVT_ADDRESS_NACK:
            MY_LOG_DEBUG("ADDRESS_NACK!");
            m_xfer_done = true;
            break;

        case NRF_DRV_TWI_EVT_DATA_NACK:
            MY_LOG_DEBUG("DATA_NACK!");
            m_xfer_done = true;
            break;

        default:
            break;
    }
}

void twi_master_init(void)
{
    ret_code_t err_code;

    const nrf_drv_twi_config_t twi_config = {
       .scl                = TWI_SCL_M,
       .sda                = TWI_SDA_M,
       .frequency          = NRF_DRV_TWI_FREQ_100K,
       .interrupt_priority = APP_IRQ_PRIORITY_HIGH,
       .clear_bus_init     = false
    };

    err_code = nrf_drv_twi_init(&m_twi, &twi_config, twi_handler, NULL);
    if (err_code != NRF_SUCCESS && err_code != NRF_ERROR_INVALID_STATE)
    {
        APP_ERROR_CHECK(err_code);
    }

    nrf_drv_twi_enable(&m_twi);
}

bool mpu6050_register_write(uint8_t register_address, uint8_t value)
{
    ret_code_t err_code;
    uint8_t tx_buf[MPU6050_ADDRESS_LEN + 1];

    tx_buf[0] = register_address;
    tx_buf[1] = value;

    m_xfer_done = false;
    err_code = nrf_drv_twi_tx(&m_twi, MPU6050_ADDRESS, tx_buf, MPU6050_ADDRESS_LEN + 1, false);
    if (err_code != NRF_SUCCESS)
    {
        return false;
    }

    if (!twi_wait_done_with_timeout())
    {
        MY_LOG_ERROR("twi tx timeout, reg=0x%02X", register_address);
        return false;
    }

    return true;
}

bool mpu6050_register_read(uint8_t register_address, uint8_t * destination, uint8_t number_of_bytes)
{
    ret_code_t err_code;

    m_xfer_done = false;
    err_code = nrf_drv_twi_tx(&m_twi, MPU6050_ADDRESS, &register_address, 1, true);
    if (err_code != NRF_SUCCESS)
    {
        return false;
    }

    if (!twi_wait_done_with_timeout())
    {
        MY_LOG_ERROR("twi tx timeout(read), reg=0x%02X", register_address);
        return false;
    }

    m_xfer_done = false;
    err_code = nrf_drv_twi_rx(&m_twi, MPU6050_ADDRESS, destination, number_of_bytes);
    if (err_code != NRF_SUCCESS)
    {
        return false;
    }

    if (!twi_wait_done_with_timeout())
    {
        MY_LOG_ERROR("twi rx timeout, reg=0x%02X", register_address);
        return false;
    }

    return true;
}

bool mpu6050_verify_product_id(void)
{
    uint8_t who_am_i;

    if (mpu6050_register_read(ADDRESS_WHO_AM_I, &who_am_i, 1))
    {
        return (who_am_i == MPU6050_WHO_AM_I);
    }

    return false;
}

bool mpu6050_init(void)
{
    if (!mpu6050_verify_product_id())
    {
        MY_LOG_DEBUG("mpu6050 id verify failed");
        return false;
    }

    if (!mpu6050_register_write(MPU_PWR_MGMT1_REG, 0x00)) return false;
    if (!mpu6050_register_write(MPU_SAMPLE_RATE_REG, 0x07)) return false;
    if (!mpu6050_register_write(MPU_CFG_REG, 0x06)) return false;
    if (!mpu6050_register_write(MPU_INT_EN_REG, 0x00)) return false;
    if (!mpu6050_register_write(MPU_GYRO_CFG_REG, 0x18)) return false;
    if (!mpu6050_register_write(MPU_ACCEL_CFG_REG, 0x00)) return false;

    return true;
}

bool MPU6050_ReadGyro(int16_t *pGYRO_X, int16_t *pGYRO_Y, int16_t *pGYRO_Z)
{
    uint8_t buf[6];

    if (mpu6050_register_read(MPU6050_GYRO_OUT, buf, 6))
    {
        *pGYRO_X = (int16_t)((buf[0] << 8) | buf[1]);
        *pGYRO_Y = (int16_t)((buf[2] << 8) | buf[3]);
        *pGYRO_Z = (int16_t)((buf[4] << 8) | buf[5]);
        return true;
    }

    return false;
}

bool MPU6050_ReadAcc(int16_t *pACC_X, int16_t *pACC_Y, int16_t *pACC_Z)
{
    uint8_t buf[6];

    if (mpu6050_register_read(MPU6050_ACC_OUT, buf, 6))
    {
        *pACC_X = (int16_t)((buf[0] << 8) | buf[1]);
        *pACC_Y = (int16_t)((buf[2] << 8) | buf[3]);
        *pACC_Z = (int16_t)((buf[4] << 8) | buf[5]);
        return true;
    }

    return false;
}

void MPU6050_data_send(void)
{
    int16_t gyro_value[3];
    char gyro_output[64];
    uint16_t send_len = 0;

    if (MPU6050_ReadGyro(&gyro_value[0], &gyro_value[1], &gyro_value[2]))
    {
        send_len = (uint16_t)snprintf(gyro_output, sizeof(gyro_output),
                                      "x=%d y=%d z=%d",
                                      gyro_value[0], gyro_value[1], gyro_value[2]);
    }
    else
    {
        send_len = (uint16_t)snprintf(gyro_output, sizeof(gyro_output), "Read Gyro failed");
    }

    if (send_len > 0)
    {
        ble_send((uint8_t *)gyro_output, send_len);
    }
}

void MPU6050_mouse_report_send(void)
{
    int16_t gx_raw = 0, gy_raw = 0, gz_raw = 0;
    char mouse_report[32];

    if (!MPU6050_ReadGyro(&gx_raw, &gy_raw, &gz_raw))
    {
        return;
    }

    float gx_dps = gx_raw / GYRO_SENSITIVITY_LSB_PER_DPS;
    float gy_dps = gy_raw / GYRO_SENSITIVITY_LSB_PER_DPS;

    if ((gx_dps < GYRO_DEADZONE_DPS) && (gx_dps > -GYRO_DEADZONE_DPS))
    {
        gx_dps = 0.0f;
    }

    if ((gy_dps < GYRO_DEADZONE_DPS) && (gy_dps > -GYRO_DEADZONE_DPS))
    {
        gy_dps = 0.0f;
    }

    int8_t dx = clamp_i8((int32_t)(gy_dps * GYRO_TO_MOUSE_GAIN));
    int8_t dy = clamp_i8((int32_t)(-gx_dps * GYRO_TO_MOUSE_GAIN));

    if (dx == 0 && dy == 0)
    {
        return;
    }

    uint16_t send_len = (uint16_t)snprintf(mouse_report, sizeof(mouse_report), "M,%d,%d\n", dx, dy);
    if (send_len > 0)
    {
        static uint16_t log_div = 0;
        if ((log_div++ % 10U) == 0U)
        {
            MY_LOG_DEBUG("mouse dx=%d dy=%d gx=%d gy=%d", dx, dy, gx_raw, gy_raw);
        }
        ble_send((uint8_t *)mouse_report, send_len);
    }
}