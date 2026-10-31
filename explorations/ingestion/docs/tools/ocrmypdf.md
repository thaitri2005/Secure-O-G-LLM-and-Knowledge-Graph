# ocrmypdf

The security documentation explicitly warns that it is not a sanitization tool for untrusted PDFs. Orientation and deskew are separate pipeline stages. Evidence: `third_party/ocrmypdf/docs/pdfsecurity.md:3-48`; `third_party/ocrmypdf/src/ocrmypdf/_pipeline.py:514-539`; `third_party/ocrmypdf/src/ocrmypdf/_pipeline.py:716-735`.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).

**ocrmypdf, ak3-scanned-well-schematic.** ocrmypdf returns 93 words on ak3-scanned-well-schematic in 4.928 seconds; count is output volume, not accuracy. OCRmyPDF changes the conductor grade from "API 5L X42" to "API SL X42". The casing endpoint becomes "B00" in OCRmyPDF instead of the printed "800". OCRmyPDF loses the "HQ" designation and starts the lower-hole label with "a (3.775") hole".

**ocrmypdf, ak3-scanned-permit-letter.** ocrmypdf returns 342 words on ak3-scanned-permit-letter in 2.984 seconds; count is output volume, not accuracy. OCRmyPDF reads the address ending as "Avenle" instead of "Avenue". The OCRmyPDF contact label is "Fox:" where the printed page says "Fax:". OCRmyPDF changes the agency domain to "www.dogec.alaska.gov".

**ocrmypdf, ak3-scanned-well-schematic: 93 words, 4.928 seconds.** OCRmyPDF changes the conductor grade from "API 5L X42" to "API SL X42". The casing endpoint becomes "B00" in OCRmyPDF instead of the printed "800". OCRmyPDF loses the "HQ" designation and starts the lower-hole label with "a (3.775") hole".

**ocrmypdf, ak3-scanned-permit-letter: 342 words, 2.984 seconds.** OCRmyPDF reads the address ending as "Avenle" instead of "Avenue". The OCRmyPDF contact label is "Fox:" where the printed page says "Fax:". OCRmyPDF changes the agency domain to "www.dogec.alaska.gov".
