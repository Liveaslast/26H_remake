# 新一轮标定、采图、辅助标注与 YOLO 训练

This is a preparation workflow, not the formal Pi runtime. The tools produce
versioned artifacts; they do not automatically replace deployed calibration or
models.

| Node | Entry / implementation | Artifact |
|---|---|---|
| Select fixed ROI | `Vision/APP/select_roi.py` | ROI numbers and preview |
| Calibrate geometry | `calibrate_geometry.py` → `Core/calibration_workflow.py` / `calibration_ui.py` | JSON, source and rectified images |
| Capture sessions | `capture_training_data.py` → `Core/dataset.py` | Images, session JSON, metadata |
| Review/import labels | `import_annotation_manifest.py` → existing dataset writer | Validated YOLO labels and updated metadata |
| Build dataset | `build_yolo_dataset.py` → `Core/dataset_tools.py` | Train/validation images, labels and manifest |
| Train | `train_yolo.py` | PT and geometry provenance |

These are preparation nodes, not a second implementation of the runtime
detector/tracker or communication session. Keep tool configuration in
`Vision/Config`, image/dataset behavior in `Vision/Core`, and device access in
`Vision/IO`; a new capability need not imply a new source file.

This workflow keeps the original calibration, captures, prepared dataset and
`Data/Training/Models/best.pt` untouched. The new work lives under
`Data/Calibration/calibration_v2/` and `Data/Training/calibration_v2/`.
Use a fresh suffix instead of `calibration_v2` for a later repeat.

## 1. Upload the Pi preparation tools

Windows PowerShell:

```powershell
cd D:\26H-remake\26H_Remake_Support
$pi = 'ikun@192.168.137.2'
$tools = '/home/ikun/vision_workspace/26H_Remake_Support'
ssh $pi "mkdir -p $tools"
scp -r .\Vision "${pi}:$tools/"
```

Upload the complete tool package so its entry points, imports and configuration
stay in sync; do not copy only one changed entry script. Close the formal camera
process before running any Support camera tool. These tools do not run the
formal app's task startup or motor control.

## 2. Calibrate on the Raspberry Pi

Use the Pi desktop terminal. First check that one fixed source ROI contains the
whole groove at all calibration angles. If the old ROI no longer does, run the
existing ROI selector and use its printed four numbers in both calibration and
capture commands. The example below retains the current ROI.

```bash
cd /home/ikun/vision_workspace/26H_Remake_Support
source /home/ikun/vision_workspace/.venv/bin/activate
python3 Vision/APP/select_roi.py \
  --camera /dev/video0 --exposure-time-absolute 80 \
  --camera-read-timeout-ms 2000 \
  --preview Data/Calibration/calibration_v2_roi_preview.png
roi=(--source-roi-x 128 --source-roi-y 425 --source-roi-width 1141 --source-roi-height 121)
python3 Vision/APP/calibrate_geometry.py \
  --camera /dev/video0 --exposure-time-absolute 80 \
  --camera-read-timeout-ms 2000 \
  --angles 12,14,16,18,20,22,24,26,28,30 --positions=-10,-5,0,5,10 \
  --output-dir Data/Calibration/calibration_v2 "${roi[@]}"
```

The operator sets and confirms each physical rod angle, then clicks the groove
corners and known positions as prompted. Angles are manually assumed, not read
from the MCU. Inspect the saved source and rectified previews before capture.
The JSON is
`/home/ikun/vision_workspace/26H_Remake_Support/Data/Calibration/calibration_v2/dynamic_calibration_manual.json`.
The script refuses to overwrite a nonempty calibration output directory.
Do not copy this JSON to the formal runtime's `assets/calibration/` yet.

## 3. Capture unlabeled photos on the Raspberry Pi

For each angle, physically hold the rod at that angle, place the ball, then run
the same command with a new angle and unique session name. The countdown starts
after camera warmup. Each run records about 40 training-input frames at 5 fps,
plus original and rectified frames and capture metadata. Collect at least two
independent ball runs per angle with varied ball positions and motion.

```bash
cd /home/ikun/vision_workspace/26H_Remake_Support
source /home/ikun/vision_workspace/.venv/bin/activate
roi=(--source-roi-x 128 --source-roi-y 425 --source-roi-width 1141 --source-roi-height 121)
angle=12
session="angle_${angle}_ball_01"
calibration=Data/Calibration/calibration_v2/dynamic_calibration_manual.json
python3 Vision/APP/capture_training_data.py \
  --calibration "$calibration" \
  --output-dir Data/Training/calibration_v2/Captures \
  --session "$session" --angle-deg "$angle" \
  --exposure-time-absolute 80 --camera-read-timeout-ms 2000 \
  --auto-capture --no-display --capture-fps 5 --duration 8 --start-delay 3 \
  "${roi[@]}"
```

Repeat with `ball_02` (and more independent runs) and with angles
12, 14, 16, 18, 20, 22, 24, 26, 28, 30. Never append a different physical
angle to a session: its metadata records a single angle. Capture an empty tube
at each angle too; the end adhesives must remain visible as hard negatives.
For an empty-tube run:

```bash
session="angle_${angle}_empty_01"
python3 Vision/APP/capture_training_data.py \
  --calibration "$calibration" \
  --output-dir Data/Training/calibration_v2/Captures \
  --session "$session" --angle-deg "$angle" \
  --exposure-time-absolute 80 --camera-read-timeout-ms 2000 \
  --auto-capture --no-display --capture-fps 5 --duration 2 "${roi[@]}"
```

This path never opens the old manual annotation UI. Photos are deliberately
saved as `unlabeled/` until reviewed locally.

## 4. Copy the complete sessions to Windows

PowerShell, run once for this fresh directory:

```powershell
cd D:\26H-remake\26H_Remake_Support
$remote = 'ikun@192.168.137.2:/home/ikun/vision_workspace/26H_Remake_Support/Data'
scp -r "$remote/Calibration/calibration_v2" .\Data\Calibration\
scp -r "$remote/Training/calibration_v2" .\Data\Training\
```

Copy full session folders, not only PNGs: the dataset builder requires
`session.json`, `metadata.jsonl`, the geometry ID and images.

## 5. Assistant labeling, then import locally

After the user reports the sessions are copied, the assistant reviews the
`unlabeled/` images and creates one CSV per session under
`Data/Training/calibration_v2/Annotations/<session>.csv`. Each manifest has
exactly `sample_id,label_state,cx,cy,w,h`; positive rows use normalized YOLO
coordinates, negative rows leave all four coordinates blank. A session manifest
must cover all of its unlabeled photos. Do not use `annotate_ball.py` or the
capture tool's manual `B`/`L` paths.

PowerShell, after those manifests exist:

```powershell
cd D:\26H-remake\26H_Remake_Support
$root = 'D:\26H-remake\26H_Remake_Support\Data\Training\calibration_v2'
foreach ($session in Get-ChildItem -LiteralPath "$root\Captures" -Directory) {
    $manifest = Join-Path "$root\Annotations" ($session.Name + '.csv')
    $importArgs = @('--session-dir', $session.FullName, '--manifest', $manifest)
    python .\Vision\APP\import_annotation_manifest.py @importArgs
    if ($LASTEXITCODE -ne 0) { throw "Label validation failed: $($session.Name)" }
}
foreach ($session in Get-ChildItem -LiteralPath "$root\Captures" -Directory) {
    $manifest = Join-Path "$root\Annotations" ($session.Name + '.csv')
    $importArgs = @('--session-dir', $session.FullName, '--manifest', $manifest, '--apply')
    python .\Vision\APP\import_annotation_manifest.py @importArgs
    if ($LASTEXITCODE -ne 0) { throw "Label import failed: $($session.Name)" }
}
```

The first loop changes nothing. The second uses the existing
`RoiDatasetWriter.label_unlabeled()` to move photos into `images/`, write YOLO
`labels/`, and update metadata. Review previews before applying.

## 6. Build and train locally

PowerShell, after every session has been imported:

```powershell
cd D:\26H-remake\26H_Remake_Support
$root = 'D:\26H-remake\26H_Remake_Support\Data\Training\calibration_v2'
$sources = foreach ($session in Get-ChildItem -LiteralPath "$root\Captures" -Directory) {
    '--source'; $session.FullName
}
$buildArgs = @('--output-dir', "$root\Prepared", '--split-mode', 'session')
python .\Vision\APP\build_yolo_dataset.py @sources @buildArgs

$trainArgs = @(
    '--data', "$root\Prepared\roi_ball.yaml",
    '--model', '.\Data\Training\Models\best.pt',
    '--project', "$root\Models\Runs", '--name', 'ball_v2',
    '--publish-dir', "$root\Models"
)
python .\Vision\APP\train_yolo.py @trainArgs
```

`--split-mode session` keeps adjacent frames in the same split. Inspect
`Prepared/manifest.json` to ensure both splits contain ball and empty-tube
sessions across useful angles. The old model is the *input* for fine-tuning;
the new `best.pt`, `last.pt` and geometry sidecars are published only in
`Data/Training/calibration_v2/Models/`. This stops at a `.pt` model. Hailo
export and replacement of the formal Pi model/calibration require a separate
validated deployment step.

## 7. Deployment is a separate boundary

Before replacing a formal model/calibration pair, verify ROI and input size,
geometry provenance, representative static/motion samples and the actual Pi
backend. A matching geometry ID is a consistency check, not proof of detection
accuracy. Archived trial reports keep their original data and conclusions;
new calibration does not retroactively validate old models or experiments.
