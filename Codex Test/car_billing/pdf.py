from __future__ import annotations

from pathlib import Path
import textwrap


PAGE_HEIGHT = 842
PAGE_WIDTH = 595
LEFT_MARGIN = 48
TOP_MARGIN = 800
FONT_SIZE = 10
LINE_HEIGHT = 14
MAX_LINES_PER_PAGE = 48


def write_text_pdf(path: Path, title: str, lines: list[str]) -> None:
    wrapped_lines = _wrap_lines([title, "", *lines])
    pages = _paginate(wrapped_lines)
    pdf_bytes = _build_pdf_bytes(pages)
    path.write_bytes(pdf_bytes)


def _wrap_lines(lines: list[str], width: int = 95) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, width=width) or [""])
    return wrapped


def _paginate(lines: list[str]) -> list[list[str]]:
    if not lines:
        return [[]]
    pages: list[list[str]] = []
    for index in range(0, len(lines), MAX_LINES_PER_PAGE):
        pages.append(lines[index : index + MAX_LINES_PER_PAGE])
    return pages


def _build_pdf_bytes(pages: list[list[str]]) -> bytes:
    objects: list[tuple[int, bytes]] = []
    objects.append((1, b"<< /Type /Catalog /Pages 2 0 R >>"))
    objects.append((2, b"<< /Type /Pages /Count 0 /Kids [] >>"))
    objects.append((3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))

    object_number = 4
    page_numbers: list[int] = []
    for page_lines in pages:
        content_number = object_number
        page_number = object_number + 1
        page_numbers.append(page_number)
        objects.append((content_number, _content_stream_object(page_lines)))
        objects.append((page_number, _page_object(content_number)))
        object_number += 2

    kids = " ".join(f"{number} 0 R" for number in page_numbers)
    objects[1] = (
        2,
        f"<< /Type /Pages /Count {len(page_numbers)} /Kids [{kids}] >>".encode("ascii"),
    )
    return _serialize_pdf(objects)


def _page_object(content_number: int) -> bytes:
    return (
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
        f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_number} 0 R >>"
    ).encode("ascii")


def _content_stream_object(lines: list[str]) -> bytes:
    commands = [
        "BT",
        f"/F1 {FONT_SIZE} Tf",
        f"{LEFT_MARGIN} {TOP_MARGIN} Td",
    ]
    first = True
    for line in lines:
        escaped = _escape_pdf_text(line)
        if first:
            commands.append(f"({escaped}) Tj")
            first = False
        else:
            commands.append(f"0 -{LINE_HEIGHT} Td")
            commands.append(f"({escaped}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", "replace")
    header = f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
    return header + stream + b"\nendstream"


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _serialize_pdf(objects: list[tuple[int, bytes]]) -> bytes:
    buffer = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in objects:
        offsets.append(len(buffer))
        buffer.extend(f"{number} 0 obj\n".encode("ascii"))
        buffer.extend(body)
        buffer.extend(b"\nendobj\n")

    xref_offset = len(buffer)
    buffer.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buffer.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    buffer.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(buffer)
