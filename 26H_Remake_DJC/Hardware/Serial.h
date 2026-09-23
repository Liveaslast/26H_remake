#ifndef __SERIAL_H
#define __SERIAL_H

#include "main.h"
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>

#ifdef __cplusplus
extern "C" {
#endif

void Serial_Init(void);
void Serial_SendByte(uint8_t Byte);
void Serial_SendArray(uint8_t *Array, uint16_t Length);
void Serial_SendString(const char *String);
void Serial_SendNumber(uint32_t Number, uint8_t Length);
void Serial_Printf(const char *format, ...);
void Serial_OnTxCplt(UART_HandleTypeDef *huart);
void Serial_OnError(UART_HandleTypeDef *huart);

uint8_t Serial_GetRxFlag(void);
uint8_t Serial_GetRxData(void);
uint8_t Serial_GetRxByte(uint8_t *data);
uint8_t Serial_GetRxOverflow(void);
void Serial_ClearRxOverflow(void);
uint8_t Serial_GetTxOverflow(void);
void Serial_ClearTxOverflow(void);

#ifdef __cplusplus
}
#endif

#endif
