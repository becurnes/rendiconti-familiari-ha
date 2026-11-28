"""Read legacy Excel cells in a process with a bounded resource budget."""

import io
import json
import resource
import struct
import sys

import xlrd

MAX_OUTPUT_BYTES = 4_000_000
TOO_LARGE = b'{"too_large":true}'


def apply_limits():
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if sys.platform == "linux":
        memory = 192 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))


def cell_text(cell, datemode):
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate_as_datetime(cell.value, datemode).date().isoformat()
        except (ValueError, OverflowError):
            return ""
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        return str(cell.value)
    return cell.value if cell.ctype == xlrd.XL_CELL_TEXT else ""


def read_workbook(raw):
    book = xlrd.open_workbook(file_contents=raw, logfile=io.StringIO(), on_demand=True,
                             ragged_rows=True, use_mmap=False)
    try:
        sheets = []
        remaining = MAX_OUTPUT_BYTES
        for sheet_index in range(min(book.nsheets, 10)):
            sheet = book.sheet_by_index(sheet_index)
            if sheet.nrows > 10_000 or sheet.ncols > 64:
                return TOO_LARGE
            records = []
            for row in sheet.get_rows():
                record = [cell_text(cell, book.datemode) for cell in row]
                encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode()
                remaining -= len(encoded) + 1
                if remaining < 0:
                    return TOO_LARGE
                records.append(encoded)
            sheets.append(b"[" + b",".join(records) + b"]")
        return b'{"sheets":[' + b",".join(sheets) + b"]}"
    finally:
        book.release_resources()


def main():
    apply_limits()
    try:
        output = read_workbook(sys.stdin.buffer.read(1_000_000))
    except (xlrd.XLRDError, xlrd.compdoc.CompDocError, struct.error, AssertionError,
            IndexError, KeyError, ValueError, OverflowError, TypeError, MemoryError):
        return 1
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
