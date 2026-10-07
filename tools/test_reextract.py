'''Synthetic-TSV acid tests for reextract.py's reconstruction core.'''
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "reextract", os.path.join(HERE, "reextract.py"))
rx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rx)


def tsv(rows):
    '''rows: list of (left, top, w, h, text, block) -> tesseract TSV text.'''
    out = ["level\tpage\tblock\tpar\tline\tword\tleft\ttop\twidth\theight\tconf\ttext"]
    for i, (l, t, w, h, txt, blk) in enumerate(rows):
        # level 5 = word; par/line left 0 (we group by geometry, not TSV lines)
        out.append("5\t1\t%d\t0\t0\t%d\t%d\t%d\t%d\t%d\t96\t%s"
                   % (blk, i + 1, l, t, w, h, txt))
    return "\n".join(out)


fails = []


def check(name, got, want):
    if got != want:
        fails.append("%s:\n  got : %r\n  want: %r" % (name, got, want))
    else:
        print("PASS %s" % name)


# 1. THE INTERLACING KILL: a 2-column table, 3 rows.
#    Naive reading order would emit all of col A then all of col B.
#    Geometry must pair them by y.
words = []
colA = [("FIGHTER", 100), ("PALADIN", 200), ("RANGER", 300)]
colB = ["d10", "d10", "d8"]
for (name, top), b in zip(colA, colB):
    words.append((100, top, 160, 20, name, 1))
    words.append((600, top + 2, 60, 20, b, 1))   # +2px jitter like real scans
got = rx.reconstruct(tsv(words), col_gap_px=100)
want = "FIGHTER | d10\nPALADIN | d10\nRANGER | d8"
check("two-column pairing", got, want)

# 2. Gap below threshold stays a plain space (no false column break).
words = [(100, 100, 80, 20, "IRON", 1), (190, 100, 60, 20, "RATION", 1)]
got = rx.reconstruct(tsv(words), col_gap_px=100)
check("small gap = space", got, "IRON RATION")

# 3. Separate blocks stay separate (two stacked tables never merge).
blk1 = [(100, 100, 80, 20, "LARGE", 1), (300, 100, 60, 20, "250", 1)]
blk2 = [(100, 300, 80, 20, "SMALL", 2), (300, 300, 60, 20, "50", 2)]
got = rx.reconstruct(tsv(blk1 + blk2), col_gap_px=100)
check("block separation", got, "LARGE | 250\n\nSMALL | 50")

# 4. Paragraph prose: no column breaks, words in x order, jittered baselines.
prose = [(100, 500, 60, 20, "The", 1), (170, 502, 80, 20, "party", 1),
         (260, 501, 120, 20, "encounters", 1), (390, 500, 40, 20, "a", 1),
         (440, 503, 60, 20, "troll", 1)]
got = rx.reconstruct(tsv(prose), col_gap_px=100)
check("prose untouched", got, "The party encounters a troll")

# 5. Three-column row (the war-machine fire table class).
words = [(100, 100, 60, 20, "BALLISTA", 1), (400, 100, 40, 20, "18", 1),
         (700, 101, 40, 20, "6", 1), (950, 99, 40, 20, "8", 1)]
got = rx.reconstruct(tsv(words), col_gap_px=100)
check("four-column row", got, "BALLISTA | 18 | 6 | 8")

# 6. Low-confidence garbage is dropped; empty TSV yields empty output.
check("conf filter", rx.parse_tsv(tsv([(1, 1, 1, 1, "junk", 1)])
                                  .replace("\t96\t", "\t-1\t")), [])
check("empty tsv", rx.reconstruct(""), "")

# 7. Line clustering: two stacked lines 40px apart must NOT merge,
#    even with a tall word on line 2.
words = [(100, 100, 80, 20, "HEADER", 1),
         (100, 140, 80, 34, "TALLROW", 1)]   # tall glyph overlapping band?
got = rx.reconstruct(tsv(words), col_gap_px=100)
check("distinct rows", got, "HEADER\nTALLROW")

# 8. Default col-gap = 5x char width fires on the wide table gap.
words = [(100, 100, 80, 20, "GNOLL", 1), (400, 100, 60, 20, "30", 1)]
got = rx.reconstruct(tsv(words))  # no explicit gap
check("default gap", got, "GNOLL | 30")

print()
if fails:
    print("%d FAIL(S)" % len(fails))
    print("\n\n".join(fails))
    sys.exit(1)
print("ALL 8 TESTS PASS")
