from html.parser import HTMLParser
from pathlib import Path


class TableReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


source = Path("projects/studio-selfcheck/reports/pricing-rendered.html")
parser = TableReader()
parser.feed(source.read_text(encoding="utf-8"))
for table_index, table in enumerate(parser.tables):
    for row_index, row in enumerate(table):
        if any("Dreamina Seedance 2.0 Mini" in cell for cell in row):
            print(f"TABLE={table_index} ROW={row_index}")
            for offset in range(max(0, row_index - 5), min(len(table), row_index + 3)):
                print(f"ROW {offset}: {table[offset]}")
