import json
from pathlib import Path
import sys

import pytest


SUPPORT_ROOT = Path(__file__).resolve().parents[2]
if str(SUPPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(SUPPORT_ROOT))

from Vision.APP.import_annotation_manifest import run  # noqa: E402


def make_session(tmp_path):
    session = tmp_path / "session"
    unlabeled = session / "unlabeled"
    unlabeled.mkdir(parents=True)
    (session / "session.json").write_text('{"geometry_id":"test"}', encoding="utf-8")
    records = []
    for index in (1, 2):
        sample_id = f"roi_{index:06d}"
        (unlabeled / f"{sample_id}.png").write_bytes(b"test-image")
        records.append({
            "sample_id": sample_id,
            "index": index,
            "label_state": "unlabeled",
            "class_id": None,
            "yolo_box_cxcywh": None,
            "paths": {"model_input": f"unlabeled/{sample_id}.png", "label": None},
        })
    (session / "metadata.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    return session


def make_manifest(tmp_path, lines):
    path = tmp_path / "annotations.csv"
    path.write_text(
        "sample_id,label_state,cx,cy,w,h\n" + "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    return path


def test_import_dry_run_then_apply(tmp_path):
    session = make_session(tmp_path)
    manifest = make_manifest(tmp_path, [
        "roi_000001,positive,0.5,0.5,0.1,0.4",
        "roi_000002,negative,,,,",
    ])
    counts = run(session, manifest, apply=False)
    assert counts == {"positive": 1, "negative": 1}
    assert len(list((session / "unlabeled").glob("*.png"))) == 2

    assert run(session, manifest, apply=True) == counts
    assert (session / "labels" / "roi_000001.txt").read_text() == "0 0.50000000 0.50000000 0.10000000 0.40000000\n"
    assert (session / "labels" / "roi_000002.txt").read_text() == ""
    assert len(list((session / "images").glob("*.png"))) == 2
    records = [json.loads(line) for line in (session / "metadata.jsonl").read_text().splitlines()]
    assert [record["label_state"] for record in records] == ["positive", "negative"]


@pytest.mark.parametrize("lines", [
    ["roi_000001,positive,0.5,0.5,0.1,0.4"],
    ["roi_000001,positive,0.95,0.5,0.2,0.4", "roi_000002,negative,,,,"],
    ["roi_000001,positive,nan,0.5,0.1,0.4", "roi_000002,negative,,,,"],
])
def test_invalid_manifest_does_not_change_session(tmp_path, lines):
    session = make_session(tmp_path)
    before = (session / "metadata.jsonl").read_bytes()
    manifest = make_manifest(tmp_path, lines)
    with pytest.raises(ValueError):
        run(session, manifest, apply=True)
    assert (session / "metadata.jsonl").read_bytes() == before
    assert len(list((session / "unlabeled").glob("*.png"))) == 2
