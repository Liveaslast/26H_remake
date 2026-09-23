#include "LED.h"

/**
 * @brief 打开 LED
 */
void LED_On(void)
{
    HAL_GPIO_WritePin(LED_GPIO_Port, LED_Pin, GPIO_PIN_SET);
}

/**
 * @brief 关闭 LED
 */
void LED_Off(void)
{
    HAL_GPIO_WritePin(LED_GPIO_Port, LED_Pin, GPIO_PIN_RESET);
}

/**
 * @brief 翻转 LED 状态
 */
void LED_Toggle(void)
{
    HAL_GPIO_TogglePin(LED_GPIO_Port, LED_Pin);
}

/**
 * @brief 延时后翻转 LED
 * @param delay_ms 延时时间，单位 ms
 */
void LED_DelayToggle(void)
{
    HAL_Delay(1000);
    HAL_GPIO_TogglePin(LED_GPIO_Port, LED_Pin);
}