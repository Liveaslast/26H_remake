# 樹莓派視覺採集工具

部署位置：`~/vision_workspace/tools/capture/`。

首次部署後：

```bash
chmod +x ~/vision_workspace/tools/capture/run_vision_probe.sh
```

使用正式 HailoRT、Wi-Fi 串流與 no-display 配置啟動，probe CSV 自動使用時間戳命名：

```bash
~/vision_workspace/tools/capture/run_vision_probe.sh
```

指定輸出文件：

```bash
~/vision_workspace/tools/capture/run_vision_probe.sh \
  ~/vision_workspace/diagnostics/vision_probe_task1.csv
```

使用 `Ctrl+C` 正常結束。此工具不更改正式配置、不設置零點，也不啟動 STM32 任務。
