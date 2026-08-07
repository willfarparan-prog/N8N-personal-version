"""Strict, dependency-free CSV validation for Batch Input uploads."""
import csv
import io

MAX_BYTES = 1024 * 1024
MAX_ROWS = 50

class BatchCsvError(ValueError): pass

def parse_batch_csv(raw: bytes) -> tuple[list[str], list[dict[str, str]]]:
    if len(raw) > MAX_BYTES: raise BatchCsvError("CSV exceeds 1 MB")
    try: text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc: raise BatchCsvError("CSV must be UTF-8") from exc
    reader = csv.reader(io.StringIO(text))
    try: headers = next(reader)
    except StopIteration: raise BatchCsvError("CSV requires a header row")
    headers = [header.strip() for header in headers]
    if not headers or any(not header for header in headers) or len(set(headers)) != len(headers):
        raise BatchCsvError("CSV headers must be non-empty and unique")
    rows = []
    for line_number, values in enumerate(reader, start=2):
        if not any(value.strip() for value in values): continue
        if len(values) != len(headers): raise BatchCsvError(f"Row {line_number} has {len(values)} values; expected {len(headers)}")
        rows.append(dict(zip(headers, values)))
        if len(rows) > MAX_ROWS: raise BatchCsvError("CSV has more than 50 non-empty rows")
    return headers, rows
