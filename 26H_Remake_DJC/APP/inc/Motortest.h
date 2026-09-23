#ifndef __MOTORTEST_H
#define __MOTORTEST_H

#include "main.h"

#ifdef __cplusplus
extern "C" {
#endif

void MotorTest_Init(void);
void MotorTest_Loop(void);
void MotorTest_OnCanRxFifo0MsgPending(CAN_HandleTypeDef *hcan);

#ifdef __cplusplus
}
#endif

#endif
