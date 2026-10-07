# tableocr

Coordinate-based PDF re-extraction for scanned book PDFs with two-column
tables. Fixes OCR table interlacing at the source: rows and columns are
rebuilt from word geometry (x/y bounding boxes), never by reading order.
Standalone tool - no ties to any other project.

## The problem this solves

Scanned books OCR'd with a reading-order extractor that
**interlaces two-column tables**: headers duplicated or misplaced, columns
run together, rows interleaved. Confirmed victims so far: the NPC personae
traits tables, the war machine fire table, the height/weight tables, the
druid spell level headers, the hire-cost lists.

## The fix: geometry, not reading order

`tools/reextract.py` renders each PDF page with `pdftoppm` (300 dpi
grayscale), OCRs it with tesseract in **TSV mode** (every word gets an
x/y bounding box), then rebuilds the page from coordinates:

- **rows**: words whose vertical centers share a y-band are one visual row
  -- both columns of a table row land on the same output line
- **columns**: an x-gap of >= 5x the median character width becomes a
  ` | ` column separator (tunable via `--col-gap`, `--sep`)
- **blocks**: tesseract block numbers keep stacked tables from merging

Text-layer (born-digital) PDFs skip OCR entirely and use `pdftotext -layout`.

## Install (Termux)

    bash termux_setup.sh

which runs `pkg install -y poppler tesseract python` -- no pip, no
compiling, everything is a native Termux package.

## Use

    # whole book
    python3 tools/reextract.py PHB.pdf phb_v2/
    
    # just the scrambled-table pages, keeping raw TSV for audits
    python3 tools/reextract.py DMG.pdf dmg_v2/ --pages 114-116,108-110 --keep-tsv
    
    # scans where a table's columns sit unusually close / far apart
    python3 tools/reextract.py DMG.pdf dmg_v2/ --pages 108-110 --col-gap 70

Outputs `out/<stem>.pNNNN.txt` per page plus `out/<stem>.full.txt`
concatenated with `=== PAGE n ===` markers. Exit code 2 warns that some
page produced no text (bad raster -- check the DPI/render).

## Tests

    python3 tools/test_reextract.py   # 8 synthetic-TSV acid tests, no deps

The tests reproduce the exact failure classes: two-column pairing, four
column rows, block separation, prose left untouched, conf filtering,
default gap calibration.

## Cross-check rule

A re-extracted table still gets cross-read against a second source
(e.g. a web compilation of the same book) before it is trusted as ground
truth -- OCR geometry fixes
interlacing, but a confirmation pass on at least the previously-scrambled
tables is mandatory before any round pins from the new extraction.
