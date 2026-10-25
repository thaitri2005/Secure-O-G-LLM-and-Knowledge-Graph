"""Explicitly download EasyOCR models before offline ingestion."""
import argparse
from importlib.metadata import version
from pathlib import Path
from .ocr_settings import ocr_settings
from .sources import sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--languages", nargs="+", default=["vi", "en"])
    parser.add_argument("--directory", type=Path, default=Path("data/interim/ocr_models"))
    args = parser.parse_args()
    settings = ocr_settings({"ocr": {"languages": args.languages}})
    import easyocr
    args.directory.mkdir(parents=True, exist_ok=True)
    easyocr.Reader(settings["languages"], gpu=False, model_storage_directory=str(args.directory),
                   download_enabled=True, verbose=False)
    hashes = {p.name: sha256(p) for p in sorted(args.directory.glob("*.pth"))}
    write_json(args.directory / "models.json", {"easyocr": version("easyocr"),
                                               "languages": settings["languages"], "sha256": hashes})
    print(f"Prepared {len(hashes)} model files for {settings['languages']}")


if __name__ == "__main__":
    main()
