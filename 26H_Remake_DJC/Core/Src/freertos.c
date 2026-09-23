/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * File Name          : freertos.c
  * Description        : Code for freertos applications
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "FreeRTOS.h"
#include "task.h"
#include "main.h"
#include "cmsis_os.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "DebugCommand.h"
#include "VisionFrame.h"
#include "BallStateEstimate.h"

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
/* USER CODE BEGIN Variables */

/* USER CODE END Variables */
/* Definitions for BlueLEDTask */
osThreadId_t BlueLEDTaskHandle;
const osThreadAttr_t BlueLEDTask_attributes = {
  .name = "BlueLEDTask",
  .stack_size = 128 * 4,
  .priority = (osPriority_t) osPriorityNormal,
};
/* Definitions for Gimbal */
osThreadId_t GimbalHandle;
const osThreadAttr_t Gimbal_attributes = {
  .name = "Gimbal",
  .stack_size = 256 * 4,
  .priority = (osPriority_t) osPriorityHigh,
};
/* Definitions for Debug */
osThreadId_t DebugHandle;
const osThreadAttr_t Debug_attributes = {
  .name = "Debug",
  .stack_size = 256 * 4,
  .priority = (osPriority_t) osPriorityNormal,
};
/* Definitions for CommunicationTa */
osThreadId_t CommunicationTaHandle;
const osThreadAttr_t CommunicationTa_attributes = {
  .name = "CommunicationTa",
  .stack_size = 512 * 4,
  .priority = (osPriority_t) osPriorityNormal1,
};
/* Definitions for BallBeamStateTa */
osThreadId_t BallBeamStateTaHandle;
const osThreadAttr_t BallBeamStateTa_attributes = {
  .name = "BallBeamStateTa",
  .stack_size = 256 * 4,
  .priority = (osPriority_t) osPriorityAboveNormal,
};
/* Definitions for DebugCommand */
osMessageQueueId_t DebugCommandHandle;
const osMessageQueueAttr_t DebugCommand_attributes = {
  .name = "DebugCommand"
};
/* Definitions for VisionFrameQueue */
osMessageQueueId_t VisionFrameQueueHandle;
const osMessageQueueAttr_t VisionFrameQueue_attributes = {
  .name = "VisionFrameQueue"
};
/* Definitions for BallStateQueue */
osMessageQueueId_t BallStateQueueHandle;
const osMessageQueueAttr_t BallStateQueue_attributes = {
  .name = "BallStateQueue"
};

/* Private function prototypes -----------------------------------------------*/
/* USER CODE BEGIN FunctionPrototypes */

/* USER CODE END FunctionPrototypes */

void StartBlueLEDTask(void *argument);
extern void GimbalTask(void *argument);
extern void DebugTask(void *argument);
extern void StartCommunicationTask(void *argument);
extern void BallStateTask(void *argument);

void MX_FREERTOS_Init(void); /* (MISRA C 2004 rule 8.1) */

/**
  * @brief  FreeRTOS initialization
  * @param  None
  * @retval None
  */
void MX_FREERTOS_Init(void) {
  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* USER CODE BEGIN RTOS_MUTEX */
  /* add mutexes, ... */
  /* USER CODE END RTOS_MUTEX */

  /* USER CODE BEGIN RTOS_SEMAPHORES */
  /* add semaphores, ... */
  /* USER CODE END RTOS_SEMAPHORES */

  /* USER CODE BEGIN RTOS_TIMERS */
  /* start timers, add new ones, ... */
  /* USER CODE END RTOS_TIMERS */

  /* Create the queue(s) */
  /* creation of DebugCommand */
  DebugCommandHandle = osMessageQueueNew (16, sizeof(DebugCommand_t), &DebugCommand_attributes);

  /* creation of VisionFrameQueue */
  VisionFrameQueueHandle = osMessageQueueNew (16, sizeof(VisionFrame_t), &VisionFrameQueue_attributes);

  /* creation of BallStateQueue */
  BallStateQueueHandle = osMessageQueueNew (8, sizeof(BallStateEstimate_t), &BallStateQueue_attributes);

  /* USER CODE BEGIN RTOS_QUEUES */
  /* add queues, ... */
  /* USER CODE END RTOS_QUEUES */

  /* Create the thread(s) */
  /* creation of BlueLEDTask */
  BlueLEDTaskHandle = osThreadNew(StartBlueLEDTask, NULL, &BlueLEDTask_attributes);

  /* creation of Gimbal */
  GimbalHandle = osThreadNew(GimbalTask, NULL, &Gimbal_attributes);

  /* creation of Debug */
  DebugHandle = osThreadNew(DebugTask, NULL, &Debug_attributes);

  /* creation of CommunicationTa */
  CommunicationTaHandle = osThreadNew(StartCommunicationTask, NULL, &CommunicationTa_attributes);

  /* creation of BallBeamStateTa */
  BallBeamStateTaHandle = osThreadNew(BallStateTask, NULL, &BallBeamStateTa_attributes);

  /* USER CODE BEGIN RTOS_THREADS */
  /* add threads, ... */
  /* USER CODE END RTOS_THREADS */

  /* USER CODE BEGIN RTOS_EVENTS */
  /* add events, ... */
  /* USER CODE END RTOS_EVENTS */

}

/* USER CODE BEGIN Header_StartBlueLEDTask */
/**
  * @brief  Function implementing the BlueLEDTask thread.
  * @param  argument: Not used
  * @retval None
  */
/* USER CODE END Header_StartBlueLEDTask */
void StartBlueLEDTask(void *argument)
{
  /* USER CODE BEGIN StartBlueLEDTask */
  /* Infinite loop */
  for(;;)
  {
    osDelay(1);
  }
  /* USER CODE END StartBlueLEDTask */
}

/* Private application code --------------------------------------------------*/
/* USER CODE BEGIN Application */

/* USER CODE END Application */

