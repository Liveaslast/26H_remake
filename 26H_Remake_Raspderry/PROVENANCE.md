# 運行包來源與校驗邊界

正式入口保持 `python3 best/run.py`，主流程現位於 `ballbeam/app/main.py`。本地來源採集 `_pi_raw_new` 曾與樹莓派正式來源逐檔核對；原機 Python/HailoRT 環境記錄在 `RUNTIME_ENVIRONMENT_RASPBERRY_PI.txt`。

| 來源位置 | 現行位置 |
|---|---|
| `best/algorithm/formal/track_ball.py` | `ballbeam/app/main.py` |
| `best/algorithm/{app,core,io,control}/` | `ballbeam/{app,vision,hardware,control}/` |
| `ball_detection_common/`、`ball_detection_runtime/` | `ballbeam/vision/detection_common/`、`detection_runtime/` |
| `best/debug_page/`、`best/WIFI_test/` | `ballbeam/interfaces/debug_page/`、`wifi_stream/` |
| `best/algorithm/config.toml` | `config/runtime.toml` |
| `best/algorithm/calibration_data/` | `assets/calibration/` |
| `best/algorithm/hailo_model/` | `assets/models/hailo/` |

正式命令的處理流程、HEF 與模型原始 metadata 未因目錄整理而更換。配置中的來源 ROI 已對齊標定 JSON 的 `(128,425,1141,121)`，並恢復相等檢查；舊配置曾寫 `(129,422,1143,124)`，但實際裁切一直由 JSON 決定。這是歷史差異，不是要使用兩套 ROI。

## 12–30°標定

生效 `assets/calibration/dynamic_calibration_12_30deg.json` 來自樹莓派原始標定輸出，`samples` 實際包含 12、14、…、30°十個角度，`geometry_id=8a5cd731dad6021704fb36f25fd423fa7ecd1634c998e23d7eaf9b13ff81126f`。補入 12°時，14–30°九個原樣本及 ROI 均未變；12°採用本身樣本，12–14°之間插值。Windows Support 保存相同 JSON 的參考副本和十組來源／展開圖。

封存的 2405 組訓練資料記錄採集時的 `geometry_id=b5db7d686fc483d125f523499dbbdb9bc71a2d9a2b7f9709992a53b8174de5ad`，未回寫。HEF 未重新編譯，模型包也沒有 `deployment.json` 可自動核對幾何 ID；不能只憑 ID 差異推斷模型好壞。

## 已驗證與未驗證

- 樹莓派：部署包 49 項 SHA-256、5 項離線測試通過；12–14°測試工作區視覺及正式 `workspace` 視覺由使用者確認正常。
- Task1：在補入 12°標定前曾跑通；本次修改後未重跑。實際 Task1 電機不進入 12°，但不應把先前結果記作修改後的新測試。
- 模型幾何：缺 `deployment.json`，只能靠實機圖像、坐標及 valid 驗證，不能宣稱自動匹配。
