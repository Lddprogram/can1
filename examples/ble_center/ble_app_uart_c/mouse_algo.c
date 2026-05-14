#include "mouse_algo.h"

static float clampf(float v, float min_v, float max_v)
{
    if (v < min_v)
    {
        return min_v;
    }
    if (v > max_v)
    {
        return max_v;
    }
    return v;
}

void mouse_algo_init(mouse_algo_state_t * state)
{
    state->filt_x = 0.0f;
    state->filt_y = 0.0f;
}

void mouse_algo_apply(const mouse_algo_config_t * cfg,
                      mouse_algo_state_t * state,
                      float gx_dps,
                      float gy_dps,
                      int8_t * out_dx,
                      int8_t * out_dy)
{
    float x = gx_dps - cfg->gyro_bias_x;
    float y = gy_dps - cfg->gyro_bias_y;

    if ((x < cfg->deadzone_dps) && (x > -cfg->deadzone_dps))
    {
        x = 0.0f;
    }
    if ((y < cfg->deadzone_dps) && (y > -cfg->deadzone_dps))
    {
        y = 0.0f;
    }

    state->filt_x = cfg->lpf_alpha * x + (1.0f - cfg->lpf_alpha) * state->filt_x;
    state->filt_y = cfg->lpf_alpha * y + (1.0f - cfg->lpf_alpha) * state->filt_y;

    x = clampf(state->filt_x * cfg->sensitivity_x, -cfg->max_speed, cfg->max_speed);
    y = clampf(state->filt_y * cfg->sensitivity_y, -cfg->max_speed, cfg->max_speed);

    *out_dx = (int8_t)x;
    *out_dy = (int8_t)y;
}
