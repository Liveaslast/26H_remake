# Uniform seven-position ball annotation trial

- Source: `../steel_ball_12_30deg_exp10/by_angle/angle_*deg_exp10`.
- Ten angles, seven images per angle. Existing YOLO label center X is used only to select evenly spaced images; `detect_ball` derives new boxes from image pixels alone.
- `images/` contains unchanged copies; `labels/` contains new class-0 YOLO boxes; `previews/` and `contact_sheets/` show new boxes in red.
- `comparison_previews/` and `comparison_sheets/` show new boxes in red and old labels in blue. `comparison.csv` contains per-image center displacement and IoU. The old labels are read only after new box estimation.
- The image-only threshold method aims to exclude diffuse shadows. Endpoint images and strong reflections remain less reliable. These are review samples, not automatically approved training labels.
