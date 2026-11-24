"""Stage the pinned Utah FORGE PDFs and Docling model bytes for an offline benchmark."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

from graph_builder.corpus.store import file_sha256


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "configs/benchmarks/forge_ddr_holdout.json"
IMAGE_REPOSITORY = "docling-project/docling-serve-cpu"
MODEL_LAYER = "24728d962da1f52fb27d18e703707f5811893ba0b4c4538186b8652dafa15451"
LAYOUT = "docling-project--docling-layout-heron"
TABLE = "docling-project--docling-models"
ARCHIVE_PREFIX = "opt/app-root/src/.cache/docling/models/"
REVISIONS = {LAYOUT: ("main", "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8"),
             TABLE: ("v2.3.0", "fc0f2d45e2218ea24bce5045f58a389aed16dc23")}
MODEL_FILES = {
    f"{LAYOUT}/config.json": "fdea30805ce2f5666b147fca941dcdd27ad468e27d6ed21902207d3da056a97d",
    f"{LAYOUT}/model.safetensors": "00333a43451945aaf89db8ca9c0a17e75d1537c17db60fdb91aa95f4c7929e0c",
    f"{LAYOUT}/preprocessor_config.json": "cd38cd59999e7a95d68e487fbe5132df3d4e5c32a0836add57e6126ba0c4eaf1",
    f"{TABLE}/model_artifacts/tableformer/fast/tableformer_fast.safetensors":
        "3119563aab5a7c96fda4d621119b63fd8806272b86c30936d15507616422f718",
    f"{TABLE}/model_artifacts/tableformer/fast/tm_config.json":
        "dca6762508dddfae6d57d6cb4ef822c6000119dff0f3b6489db7413118c2622a",
}


def verify(path, expected):
    if file_sha256(path) != expected:
        raise ValueError(f"SHA-256 mismatch: {path}")


def copy_verified(source, target, expected):
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=target.parent) as temporary:
        staged = Path(temporary) / target.name
        shutil.copyfile(source, staged)
        verify(staged, expected)
        staged.replace(target)


def stage_pdfs(checkout, destination):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    if commit != manifest["revision"]:
        raise ValueError(f"expected dataset revision {manifest['revision']}, got {commit}")
    destination.mkdir(parents=True, exist_ok=True)
    for row in manifest["documents"]:
        path = destination / row["file"]
        if not path.exists():
            source = checkout / "book/datasets/forge_archive" / row["file"]
            copy_verified(source, path, row["sha256"])
        verify(path, row["sha256"])
    print(f"Verified {len(manifest['documents'])} source PDFs in {destination}", flush=True)


def download_layer(path):
    base = "https://ghcr.io"
    token_url = f"{base}/token?service=ghcr.io&scope=repository:{IMAGE_REPOSITORY}:pull"
    with urlopen(token_url, timeout=20) as response:
        token = json.load(response)["token"]
    request = Request(f"{base}/v2/{IMAGE_REPOSITORY}/blobs/sha256:{MODEL_LAYER}")
    request.add_unredirected_header("Authorization", f"Bearer {token}")
    with urlopen(request, timeout=90) as response, path.open("wb") as target:
        shutil.copyfileobj(response, target, 1024 * 1024)


def model_paths(cache):
    targets = {}
    for name in MODEL_FILES:
        folder, relative = name.split("/", 1)
        revision = REVISIONS[folder][1]
        targets[name] = cache / f"models--{folder}" / "snapshots" / revision / relative
    return targets


def stage_models(cache, local_layer):
    targets = model_paths(cache)
    missing = set()
    for name, path in targets.items():
        if path.exists():
            verify(path, MODEL_FILES[name])
        else:
            missing.add(name)
    if missing:
        with TemporaryDirectory(prefix="forge-docling-models-") as temporary:
            scratch = Path(temporary)
            layer = local_layer or (scratch / "models.tar.gz")
            if not local_layer:
                download_layer(layer)
            verify(layer, MODEL_LAYER)
            with tarfile.open(layer, "r|gz") as archive:
                for member in archive:
                    name = member.name.removeprefix(ARCHIVE_PREFIX)
                    if not member.isfile() or name not in missing or not member.name.startswith(ARCHIVE_PREFIX):
                        continue
                    target = scratch / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    verify(target, MODEL_FILES[name])
            for name in missing:
                verify(scratch / name, MODEL_FILES[name])
            for name in missing:
                copy_verified(scratch / name, targets[name], MODEL_FILES[name])
    for folder, (ref, revision) in REVISIONS.items():
        pointer = cache / f"models--{folder}" / "refs" / ref
        pointer.parent.mkdir(parents=True, exist_ok=True)
        if pointer.exists() and pointer.read_text(encoding="utf-8").strip() != revision:
            raise ValueError(f"cache ref points to a different revision: {pointer}")
        if not pointer.exists():
            pointer.write_text(revision, encoding="utf-8")
    print(f"Verified {len(MODEL_FILES)} model files in {cache}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-checkout", type=Path, required=True)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--hf-cache", type=Path, required=True)
    parser.add_argument("--model-layer", type=Path, help="local copy of the pinned compressed OCI layer")
    arguments = parser.parse_args()
    stage_pdfs(arguments.dataset_checkout, arguments.pdf_dir)
    stage_models(arguments.hf_cache, arguments.model_layer)


if __name__ == "__main__":
    main()
