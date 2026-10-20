from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


trial = Path(__file__).resolve().parent
source = trial.parent / "steel_ball_12_30deg_exp10" / "by_angle"
preview_dir = trial / "previews"
image_dir = trial / "images"
preview_dir.mkdir(exist_ok=True)
image_dir.mkdir(exist_ok=True)
panels = []

for label_path in sorted((trial / "labels").glob("*.txt")):
    angle, frame = label_path.stem.split("_roi_")
    source_image = source / f"{angle}deg_exp10" / "images" / f"roi_{frame}.png"
    image = Image.open(source_image).convert("RGB")
    image.save(image_dir / label_path.with_suffix(".png").name)
    _, cx, cy, bw, bh = map(float, label_path.read_text().split())
    width, height = image.size
    box = ((cx - bw / 2) * width, (cy - bh / 2) * height,
           (cx + bw / 2) * width, (cy + bh / 2) * height)
    draw = ImageDraw.Draw(image)
    draw.rectangle(box, outline=(255, 45, 35), width=2)
    draw.text((4, 3), label_path.stem, fill=(255, 45, 35), font=ImageFont.load_default())
    image.save(preview_dir / label_path.with_suffix(".png").name)
    panels.append(image)

sheet = Image.new("RGB", (640, 128 * len(panels)), "white")
for index, panel in enumerate(panels):
    sheet.paste(panel, (0, 128 * index))
sheet.save(trial / "contact_sheet.png")
print(f"Rendered {len(panels)} annotations to {trial}")
