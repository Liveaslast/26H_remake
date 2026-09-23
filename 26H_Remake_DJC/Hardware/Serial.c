#include "Serial.h"

#define SERIAL_RX_BUFFER_SIZE 128U
#define SERIAL_TX_BUFFER_SIZE 2048U

extern UART_HandleTypeDef huart6;

#define DEBUG_UART_HANDLE huart6
#define DEBUG_UART_INSTANCE USART6


uint8_t Serial_RxData;
uint8_t Serial_RxFlag;
static volatile uint8_t Serial_RxBuffer[SERIAL_RX_BUFFER_SIZE];
static volatile uint16_t Serial_RxHead = 0U;
static volatile uint16_t Serial_RxTail = 0U;
static volatile uint8_t Serial_RxOverflow = 0U;
static uint8_t Serial_TxBuffer[SERIAL_TX_BUFFER_SIZE];
static volatile uint16_t Serial_TxHead = 0U;
static volatile uint16_t Serial_TxTail = 0U;
static volatile uint16_t Serial_TxDmaLength = 0U;
static volatile uint8_t Serial_TxBusy = 0U;
static volatile uint8_t Serial_TxOverflow = 0U;

static uint32_t Serial_EnterCritical(void)
{
    uint32_t primask = __get_PRIMASK();
    __disable_irq();
    return primask;
}

static void Serial_ExitCritical(uint32_t primask)
{
    if (primask == 0U) {
        __enable_irq();
    }
}

static uint32_t Serial_Pow(uint32_t X, uint32_t Y)
{
    uint32_t Result = 1U;

    while (Y--) {
        Result *= X;
    }

    return Result;
}

static void Serial_RxBufferPush(uint8_t data)
{
    uint16_t nextHead = (uint16_t)((Serial_RxHead + 1U) % SERIAL_RX_BUFFER_SIZE);

    if (nextHead == Serial_RxTail) {
        Serial_RxOverflow = 1U;
        return;
    }

    Serial_RxBuffer[Serial_RxHead] = data;
    Serial_RxHead = nextHead;
    Serial_RxFlag = 1U;
}

static void Serial_TryStartTxDma(void)
{
    uint16_t tail;
    uint16_t length;
    uint32_t primask;

    primask = Serial_EnterCritical();
    if ((Serial_TxBusy != 0U) || (Serial_TxHead == Serial_TxTail)) {
        Serial_ExitCritical(primask);
        return;
    }

    tail = Serial_TxTail;
    length = (Serial_TxHead > Serial_TxTail)
                 ? (uint16_t)(Serial_TxHead - Serial_TxTail)
                 : (uint16_t)(SERIAL_TX_BUFFER_SIZE - Serial_TxTail);
    Serial_TxDmaLength = length;
    Serial_TxBusy = 1U;
    Serial_ExitCritical(primask);

    if (HAL_UART_Transmit_DMA(&DEBUG_UART_HANDLE, &Serial_TxBuffer[tail], length) != HAL_OK) {
        primask = Serial_EnterCritical();
        Serial_TxBusy = 0U;
        Serial_TxDmaLength = 0U;
        Serial_ExitCritical(primask);
    }
}

static void Serial_TxBufferPush(uint8_t data)
{
    uint16_t nextHead;
    uint8_t overflow = 0U;
    uint32_t primask;

    primask = Serial_EnterCritical();
    nextHead = (uint16_t)((Serial_TxHead + 1U) % SERIAL_TX_BUFFER_SIZE);
    if (nextHead == Serial_TxTail) {
        Serial_TxOverflow = 1U;
        overflow = 1U;
    } else {
        Serial_TxBuffer[Serial_TxHead] = data;
        Serial_TxHead = nextHead;
    }
    Serial_ExitCritical(primask);

    if (overflow == 0U) {
        Serial_TryStartTxDma();
    }
}

void Serial_Init(void)
{
    Serial_RxHead = 0U;
    Serial_RxTail = 0U;
    Serial_RxFlag = 0U;
    Serial_RxOverflow = 0U;
    Serial_TxHead = 0U;
    Serial_TxTail = 0U;
    Serial_TxDmaLength = 0U;
    Serial_TxBusy = 0U;
    Serial_TxOverflow = 0U;
    (void)HAL_UART_Receive_IT(&DEBUG_UART_HANDLE, &Serial_RxData, 1U);
}

void Serial_SendByte(uint8_t Byte)
{
    Serial_TxBufferPush(Byte);
}

void Serial_SendArray(uint8_t *Array, uint16_t Length)
{
    uint16_t i;

    if (Array == NULL) {
        return;
    }

    for (i = 0U; i < Length; i++) {
        Serial_SendByte(Array[i]);
    }
}

void Serial_SendString(const char *String)
{
    uint16_t i;

    if (String == NULL) {
        return;
    }

    for (i = 0U; String[i] != '\0'; i++) {
        Serial_SendByte((uint8_t)String[i]);
    }
}

void Serial_SendNumber(uint32_t Number, uint8_t Length)
{
    uint8_t i;

    for (i = 0U; i < Length; i++) {
        Serial_SendByte((uint8_t)(Number / Serial_Pow(10U, (uint32_t)(Length - i - 1U)) % 10U + '0'));
    }
}

int fputc(int ch, FILE *f)
{
    (void)f;
    Serial_SendByte((uint8_t)ch);
    return ch;
}

void Serial_Printf(const char *format, ...)
{
    char String[128];
    va_list arg;

    if (format == NULL) {
        return;
    }

    va_start(arg, format);
    (void)vsnprintf(String, sizeof(String), format, arg);
    va_end(arg);
    Serial_SendString(String);
}

uint8_t Serial_GetRxFlag(void)
{
    uint8_t hasData;
    uint32_t primask;

    primask = Serial_EnterCritical();
    hasData = (Serial_RxHead != Serial_RxTail) ? 1U : 0U;
    Serial_ExitCritical(primask);

    return hasData;
}

uint8_t Serial_GetRxData(void)
{
    uint8_t data = 0U;

    (void)Serial_GetRxByte(&data);

    return data;
}

uint8_t Serial_GetRxByte(uint8_t *data)
{
    uint8_t hasData = 0U;
    uint32_t primask;

    if (data == NULL) {
        return 0U;
    }

    primask = Serial_EnterCritical();
    if (Serial_RxHead != Serial_RxTail) {
        *data = Serial_RxBuffer[Serial_RxTail];
        Serial_RxTail = (uint16_t)((Serial_RxTail + 1U) % SERIAL_RX_BUFFER_SIZE);
        hasData = 1U;
    }
    Serial_RxFlag = (Serial_RxHead != Serial_RxTail) ? 1U : 0U;
    Serial_ExitCritical(primask);

    return hasData;
}

uint8_t Serial_GetRxOverflow(void)
{
    return Serial_RxOverflow;
}

void Serial_ClearRxOverflow(void)
{
    Serial_RxOverflow = 0U;
}

uint8_t Serial_GetTxOverflow(void)
{
    return Serial_TxOverflow;
}

void Serial_ClearTxOverflow(void)
{
    Serial_TxOverflow = 0U;
}

void Serial_OnTxCplt(UART_HandleTypeDef *huart)
{
    if (huart->Instance != DEBUG_UART_INSTANCE) {
        return;
    }

    uint32_t primask = Serial_EnterCritical();
    Serial_TxTail = (uint16_t)((Serial_TxTail + Serial_TxDmaLength) % SERIAL_TX_BUFFER_SIZE);
    Serial_TxDmaLength = 0U;
    Serial_TxBusy = 0U;
    Serial_ExitCritical(primask);

    Serial_TryStartTxDma();
}

void Serial_OnError(UART_HandleTypeDef *huart)
{
    if (huart->Instance != DEBUG_UART_INSTANCE) {
        return;
    }

    __HAL_UNLOCK(huart);
    uint32_t primask = Serial_EnterCritical();
    Serial_TxDmaLength = 0U;
    Serial_TxBusy = 0U;
    Serial_ExitCritical(primask);
    Serial_TryStartTxDma();
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == DEBUG_UART_INSTANCE) {
        Serial_RxBufferPush(Serial_RxData);
        (void)HAL_UART_Receive_IT(&DEBUG_UART_HANDLE, &Serial_RxData, 1U);
    }
}
