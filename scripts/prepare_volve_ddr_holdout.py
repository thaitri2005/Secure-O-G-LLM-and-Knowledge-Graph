"""Rebuild the pinned Volve daily-report bundles from their source PDFs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from urllib.request import urlopen

import pymupdf

from graph_builder.corpus.store import file_sha256


def stage_bundles(manifest: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    settings = json.loads(manifest.read_text(encoding="utf-8"))
    with TemporaryDirectory(dir=target) as tmp:
        staging = Path(tmp)
        for spec in settings["documents"]:
            name = Path(spec["file"]).name
            output = target / name
            if output.exists() and file_sha256(output) == spec["sha256"]:
                continue
            with pymupdf.open() as bundle:
                for source in spec["source_pages"]:
                    path = staging / Path(source["file"]).name
                    with urlopen(source["source_url"], timeout=45) as response, path.open("wb") as stream:
                        shutil.copyfileobj(response, stream)
                    if file_sha256(path) != source["sha256"]:
                        raise ValueError(f"Unexpected source PDF digest: {source['file']}")
                    with pymupdf.open(path) as original:
                        if len(original) != source["pages"] or bundle.page_count + 1 != source["first_bundle_page"]:
                            raise ValueError(f"Unexpected source pagination: {source['file']}")
                        bundle.insert_pdf(original)
                if len(bundle) != spec["pages"]:
                    raise ValueError(f"Unexpected bundle pagination: {name}")
                built = staging / name
                bundle.save(built, no_new_id=True, garbage=4, deflate=True)
            if file_sha256(built) != spec["sha256"]:
                raise ValueError(f"Unexpected bundle digest: {name}")
            built.replace(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("configs/benchmarks/track_a_volve_holdout.json"))
    parser.add_argument("--pdf-dir", type=Path, required=True)
    args = parser.parse_args()
    stage_bundles(args.manifest, args.pdf_dir)
