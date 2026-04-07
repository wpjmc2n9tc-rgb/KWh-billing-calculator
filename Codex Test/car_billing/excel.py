from __future__ import annotations

from io import BytesIO
import re
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"m": MAIN_NS, "r": REL_NS, "p": PACKAGE_REL_NS}


def read_xlsx_rows(content: bytes, preferred_sheet_name: str | None = None) -> list[dict[str, Any]]:
    with ZipFile(BytesIO(content)) as workbook:
        shared_strings = _load_shared_strings(workbook)
        sheet_path = _resolve_sheet_path(workbook, preferred_sheet_name)
        raw_rows = _read_sheet_rows(workbook.read(sheet_path), shared_strings)
    return _rows_to_dicts(raw_rows)


def _load_shared_strings(workbook: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []
    root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("m:si", NS):
        text_parts = [node.text or "" for node in item.findall(".//m:t", NS)]
        strings.append("".join(text_parts))
    return strings


def _resolve_sheet_path(workbook: ZipFile, preferred_sheet_name: str | None) -> str:
    workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
    rels_root = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    relationships = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels_root.findall("p:Relationship", NS)
    }
    sheets = workbook_root.findall("m:sheets/m:sheet", NS)
    if not sheets:
        raise ValueError("The workbook does not contain any sheets.")

    selected = sheets[0]
    if preferred_sheet_name:
        for sheet in sheets:
            if sheet.attrib.get("name") == preferred_sheet_name:
                selected = sheet
                break

    relation_id = selected.attrib.get(f"{{{REL_NS}}}id")
    if not relation_id or relation_id not in relationships:
        raise ValueError("The workbook sheet relationship is missing.")

    target = relationships[relation_id].lstrip("/")
    if not target.startswith("xl/"):
        target = f"xl/{target.lstrip('./')}"
    return target


def _read_sheet_rows(sheet_xml: bytes, shared_strings: list[str]) -> list[list[Any]]:
    root = ET.fromstring(sheet_xml)
    rows: list[list[Any]] = []
    for row in root.findall(".//m:sheetData/m:row", NS):
        values: dict[int, Any] = {}
        max_index = -1
        for cell in row.findall("m:c", NS):
            reference = cell.attrib.get("r", "A1")
            column_letters = re.sub(r"\d", "", reference)
            index = _column_index(column_letters)
            values[index] = _cell_value(cell, shared_strings)
            max_index = max(max_index, index)
        if max_index < 0:
            continue
        ordered = [None] * (max_index + 1)
        for index, value in values.items():
            ordered[index] = value
        rows.append(ordered)
    return rows


def _column_index(column_letters: str) -> int:
    result = 0
    for letter in column_letters:
        result = (result * 26) + (ord(letter.upper()) - ord("A") + 1)
    return max(result - 1, 0)


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> Any:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        text_nodes = cell.findall("m:is//m:t", NS)
        return "".join(node.text or "" for node in text_nodes)

    value_node = cell.find("m:v", NS)
    if value_node is None or value_node.text is None:
        return None

    raw_value = value_node.text
    if cell_type == "s":
        return shared_strings[int(raw_value)]
    if cell_type == "str":
        return raw_value
    return _parse_numeric(raw_value)


def _parse_numeric(raw_value: str) -> Any:
    try:
        if "." in raw_value:
            return float(raw_value)
        return int(raw_value)
    except ValueError:
        return raw_value


def _rows_to_dicts(raw_rows: list[list[Any]]) -> list[dict[str, Any]]:
    if not raw_rows:
        return []

    headers = [str(value).strip() if value is not None else "" for value in raw_rows[0]]
    rows: list[dict[str, Any]] = []
    for raw_row in raw_rows[1:]:
        if all(value in (None, "") for value in raw_row):
            continue
        row: dict[str, Any] = {}
        for index, header in enumerate(headers):
            if not header:
                continue
            row[header] = raw_row[index] if index < len(raw_row) else None
        rows.append(row)
    return rows
