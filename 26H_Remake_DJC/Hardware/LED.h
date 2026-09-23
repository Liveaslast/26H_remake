#ifndef _LED_H_
#define _LED_H_

#include "main.h"

#define LED_GPIO_Port   GPIOH
#define LED_Pin         GPIO_PIN_10

void LED_On(void);
void LED_Off(void);
void LED_Toggle(void);
void LED_DelayToggle(void);


#endif