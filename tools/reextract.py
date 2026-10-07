#!/usr/bin/env python3
'''reextract.py -- coordinate-based PDF re-extraction for scanned book PDFs.

WHY THIS EXISTS
  Scanned books OCR'd with a reading-order extractor that
  INTERLACES two-column tables (headers duplicated/misplaced, columns run
  together -- the personae tables, the war machine fire table, the height/
  weight tables). This tool re-extracts from the PDFs using word GEOMETRY:
  every OCR word carries an (x, y) bounding box, and lines/columns are
  rebuilt from those coordinates, so table cells land in the correct column
  by POSITION, never by reading order.

PIPELINE (all Termux-native, zero pip):
  1. pdftoppm  (poppler)  renders each page to a 300-dpi grayscale image
  2. tesseract           OCRs each page to TSV (one word per line + bbox)
  3. this script         rebuilds rows by y-overlap and columns by x-gaps

Text-layer PDFs (born-digital) skip OCR and use `pdftotext -layout` instead.

USAGE
  python3 tools/reextract.py book.pdf out_dir/          # auto mode (recommended)
  python3 tools/reextract.py book.pdf out_dir/ --force-ocr
  python3 tools/reextract.py book.pdf out_dir/ --pages 114-116
  python3 tools/reextract.py book.pdf out_dir/ --col-gap 80 --sep '\t'

OUTPUT
  out_dir/<stem>.full.txt      all pages concatenated (=== PAGE n === markers)
  out_dir/<stem>.pNNNN.txt     one file per page (raw TSV kept as .pNNNN.tsv
                               when --keep-tsv is passed -- useful for audits)

EXIT CODE
  0 on success; 2 on a page that produced no text at all (likely a bad
  render -- check the raster); 1 on usage/subprocess errors.
'''

import argparse
import os
import shutil
import statistics
import subprocess
import sys
import tempfile

# --- TSV reconstruction core (pure stdlib, unit-testable) ------------------


def parse_tsv(text):
    '''Parse tesseract TSV output into a list of word dicts.'''
    words = []
    lines = text.splitlines()
    # find the header row (tesseract emits: level page block par line word ...)
    start = 0
    for i, ln in enumerate(lines):
        if ln.split("\t")[:1] == ["level"]:
            start = i + 1
            break
    for ln in lines[start:]:
        cols = ln.split("\t")
        if len(cols) < 12:
            continue
        try:
            level = int(cols[0])
            left, top, width, height = (int(cols[6]), int(cols[7]),
                                        int(cols[8]), int(cols[9]))
            conf = float(cols[10])
        except ValueError:
            continue
        txt = cols[11] if len(cols) > 11 else ""
        if level == 5 and txt.strip() and conf >= 0:
            words.append({
                "block": int(cols[2]), "par": int(cols[3]),
                "line": int(cols[4]),
                "left": left, "top": top, "w": width, "h": height,
                "conf": conf, "text": txt.strip(),
            })
    return words


def _char_width(words):
    '''Median per-character width across all words (pixel estimate).'''
    est = []
    for w in words:
        n = max(len(w["text"]), 1)
        est.append(w["w"] / n)
    if not est:
        return 10.0
    return statistics.median(est)


def group_lines(words):
    '''Cluster words into visual lines by y-overlap.

    Words whose vertical center falls within a line's running band are the
    same row -- this is what kills interlacing: two columns of the same
    table row share a y-band, so they end up on ONE output line, side by
    side in x order, instead of being read as separate runs of text.
    '''
    if not words:
        return []
    for w in words:
        w["cy"] = w["top"] + w["h"] / 2.0
    words.sort(key=lambda w: (w["cy"], w["left"]))
    lines = []  # each: {"cy": float, "top":, "h":, "words": []}
    for w in words:
        if lines:
            ln = lines[-1]
            tol = 0.6 * max(w["h"], statistics.median(
                [x["h"] for x in ln["words"]] + [w["h"]]))
            if abs(w["cy"] - ln["cy"]) <= tol:
                ln["words"].append(w)
                # running mean keeps the band centered on the row
                ln["cy"] = statistics.mean([x["cy"] for x in ln["words"]])
                continue
        lines.append({"cy": w["cy"], "words": [w]})
    # keep page reading order: sort by vertical center, then rebuild
    lines.sort(key=lambda l: l["cy"])
    for ln in lines:
        ln["words"].sort(key=lambda w: w["left"])
    return lines


def render_line(words, col_gap_px, sep):
    '''Emit one reconstructed line; large x-gaps become column separators.'''
    out = []
    prev = None
    cw = _char_width(words)
    for w in words:
        if prev is not None:
            gap = w["left"] - (prev["left"] + prev["w"])
            if gap >= col_gap_px:
                out.append(sep)
            else:
                out.append(" ")
        out.append(w["text"])
        prev = w
    return "".join(out).rstrip()


def reconstruct(tsv_text, col_gap_px=None, sep=" | "):
    '''TSV text -> page text with geometry-based rows and column breaks.'''
    words = parse_tsv(tsv_text)
    if not words:
        return ""
    if col_gap_px is None:
        # default: 5x the median char width -- wide enough to fire between
        # table columns, narrow enough to never fire inside a word run
        col_gap_px = 5.0 * _char_width(words)
    # split by block first so separate table blocks never merge
    blocks = {}
    for w in words:
        blocks.setdefault(w["block"], []).append(w)
    block_texts = []
    for bnum in sorted(blocks):
        blines = group_lines(blocks[bnum])
        block_texts.append("\n".join(
            render_line(ln["words"], col_gap_px, sep) for ln in blines))
    return "\n\n".join(block_texts)


# --- PDF processing ----------------------------------------------------------


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        sys.stderr.write("command failed: %s\n%s" % (" ".join(cmd), p.stderr))
        raise SystemExit(1)
    return p.stdout


def page_range(spec, total):
    ''''114-116,120' -> [113,114,115,119] (0-based), clamped.'''
    pages = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            pages.update(range(int(a), int(b) + 1))
        else:
            pages.add(int(part))
    return sorted(p - 1 for p in pages if 1 <= p <= total)


def count_pages(pdf):
    out = run(["pdfinfo", pdf])
    for ln in out.splitlines():
        if ln.startswith("Pages:"):
            return int(ln.split()[-1])
    raise SystemExit("pdfinfo: no page count for %s" % pdf)


def has_text_layer(pdf, sample=3):
    '''True if pdftotext finds real text on sampled pages.'''
    total = count_pages(pdf)
    picks = sorted({0, total // 2, total - 1})
    got = 0
    for pg in picks:
        out = run(["pdftotext", "-f", str(pg + 1), "-l", str(pg + 1),
                   pdf, "-"])
        if len(out.strip()) > 200:
            got += 1
    return got == len(picks)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf")
    ap.add_argument("out_dir")
    ap.add_argument("--pages", help="page spec, e.g. 114-116,120 (1-based)")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--col-gap", type=float, default=None,
                    help="x-gap in px that means a column break "
                         "(default: 5x median char width)")
    ap.add_argument("--sep", default=" | ",
                    help="column separator emitted in output (default ' | ')")
    ap.add_argument("--force-ocr", action="store_true",
                    help="OCR even if the PDF has a text layer")
    ap.add_argument("--keep-tsv", action="store_true",
                    help="keep raw per-page TSV next to the output")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and stop")
    args = ap.parse_args()

    if args.sep == "\\t":
        args.sep = "\t"
    os.makedirs(args.out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.pdf))[0]
    total = count_pages(args.pdf)
    use_ocr = args.force_ocr or not has_text_layer(args.pdf)
    pages = page_range(args.pages, total) if args.pages else list(range(total))

    plan = "mode=%s pages=%d/%d dpi=%d" % (
        "OCR(tesseract)" if use_ocr else "text-layer(pdftotext)",
        len(pages), total, args.dpi)
    print(plan)
    if args.dry_run:
        return 0

    tmp = tempfile.mkdtemp(prefix="reextract-")
    empty_pages = []
    full = []
    try:
        for pg in pages:
            n = pg + 1
            tag = "%s.p%04d" % (stem, n)
            if use_ocr:
                img = os.path.join(tmp, "pg")
                run(["pdftoppm", "-gray", "-r", str(args.dpi),
                     "-f", str(n), "-l", str(n), args.pdf, img])
                real = os.path.join(tmp, "pg-%d" % n)
                if not os.path.exists(real):
                    real = os.path.join(tmp, "pg-%02d" % n)
                tsv = run(["tesseract", real, "-", "-c",
                           "tessedit_create_tsv=1", "tsv"])
                if args.keep_tsv:
                    with open(os.path.join(args.out_dir, tag + ".tsv"),
                              "w") as fh:
                        fh.write(tsv)
                text = reconstruct(tsv, args.col_gap, args.sep)
            else:
                text = run(["pdftotext", "-layout", "-f", str(n),
                            "-l", str(n), args.pdf, "-"])
            if not text.strip():
                empty_pages.append(n)
            with open(os.path.join(args.out_dir, tag + ".txt"), "w") as fh:
                fh.write(text + "\n")
            full.append("=== PAGE %d ===\n%s" % (n, text))
            print("  page %d: %d chars" % (n, len(text)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    with open(os.path.join(args.out_dir, stem + ".full.txt"), "w") as fh:
        fh.write("\n\n".join(full) + "\n")
    if empty_pages:
        print("WARNING: %d page(s) produced NO text: %s" %
              (len(empty_pages), ", ".join(map(str, empty_pages[:10]))))
        return 2
    print("OK: wrote %s" % os.path.join(args.out_dir, stem + ".full.txt"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
