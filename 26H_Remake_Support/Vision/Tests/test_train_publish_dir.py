import json
from argparse import Namespace
from pathlib import Path
import sys
from types import SimpleNamespace


SUPPORT_ROOT = Path(__file__).resolve().parents[2]
if str(SUPPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(SUPPORT_ROOT))

from Vision.APP.train_yolo import run  # noqa: E402


def test_publish_dir_does_not_change_base_model(tmp_path, monkeypatch):
    prepared = tmp_path / "Prepared"
    prepared.mkdir()
    (prepared / "roi_ball.yaml").write_text("names: {0: steel_ball}\n", encoding="utf-8")
    (prepared / "manifest.json").write_text(json.dumps({
        "image_size": {"width": 640, "height": 128},
        "geometry_id": "a" * 64,
    }), encoding="utf-8")
    base_model = tmp_path / "old_best.pt"
    base_model.write_bytes(b"old-model")
    run_dir = tmp_path / "Runs" / "trial"
    run_dir.mkdir(parents=True)
    best = run_dir / "best.pt"
    last = run_dir / "last.pt"
    best.write_bytes(b"new-best")
    last.write_bytes(b"new-last")

    class FakeYOLO:
        def __init__(self, model, task):
            self.trainer = None

        def train(self, **kwargs):
            self.trainer = SimpleNamespace(best=best, last=last, save_dir=run_dir)

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        __version__="test", cuda=SimpleNamespace(is_available=lambda: False)
    ))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(
        __version__="test", YOLO=FakeYOLO
    ))
    args = Namespace(
        data=prepared / "roi_ball.yaml", model=base_model,
        epochs=1, batch=2, imgsz=640, device="auto", workers=0,
        patience=1, seed=42, project=tmp_path / "Runs", name="trial",
        resume_from=None, cache="none", publish_dir=tmp_path / "NewModels",
    )
    published = run(args)
    assert published == tmp_path / "NewModels" / "best.pt"
    assert published.read_bytes() == b"new-best"
    assert (published.parent / "last.pt").read_bytes() == b"new-last"
    assert base_model.read_bytes() == b"old-model"
    assert (published.with_suffix(".pt.geometry.json")).is_file()
