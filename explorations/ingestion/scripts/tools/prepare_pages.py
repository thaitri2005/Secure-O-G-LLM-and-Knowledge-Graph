"""Create content-named source slices and renders for tool comparisons."""
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE / 'src'))
from ingest_prototype.runtime import ROOT, read, digest


def main() -> None:
    from pypdf import PdfReader, PdfWriter
    import pypdfium2
    directory = BASE / 'runs/pages'
    directory.mkdir(parents=True, exist_ok=True)
    settings = read(BASE / 'configs/pages.json')
    for case in settings['cases']:
        source = ROOT / 'data/raw' / (case['doc_id'] + '.pdf')
        if digest(source) != case['sha256']:
            raise ValueError('Source PDF differs from its pin')
        reader, writer = PdfReader(source), PdfWriter()
        with pypdfium2.PdfDocument(source) as document:
            for page in case['pages']:
                writer.add_page(reader.pages[page - 1])
                document[page - 1].render(scale=settings['dpi'] / 72).to_pil().save(directory / f"{case['id']}-p{page}.png")
        writer.write(directory / (case['id'] + '.pdf'))
    print('Source slices and renders prepared.')


if __name__ == '__main__':
    main()
