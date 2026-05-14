#ifndef MOUSE_ALGO_H
#define MOUSE_ALGO_H

#include <stdint.h>

typedef struct
{
    float gyro_bias_x;
    float gyro_bias_y;
    float gyro_bias_z;
    float lpf_alpha;
    float sensitivity_x;
    float sensitivity_y;
    float deadzone_dps;
    float max_speed;
} mouse_algo_config_t;

typedef struct
{
    float filt_x;
    float filt_y;
} mouse_algo_state_t;

void mouse_algo_init(mouse_algo_state_t * state);
void mouse_algo_apply(const mouse_algo_config_t * cfg,
                      mouse_algo_state_t * state,
                      float gx_dps,
                      float gy_dps,
                      int8_t * out_dx,
                      int8_t * out_dy);

#endif
