"""Small, explicit post markup -> Telegram entities (no HTML interpretation)."""
from __future__ import annotations

from dataclasses import dataclass


class MarkupError(ValueError):
    pass


@dataclass(frozen=True)
class Span:
    type: str
    offset: int
    length: int


@dataclass(frozen=True)
class FormattedPost:
    text: str
    entities: tuple[Span, ...]


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def parse_post(source: str) -> FormattedPost:
    """Support **bold**, __underline__, _italic_, ~~strike~~, ||spoiler||, `code`."""
    if not source.strip():
        raise MarkupError("Пришли непустой текст")
    markers = {"**": "bold", "__": "underline", "_": "italic",
               "~~": "strikethrough", "||": "spoiler"}
    output: list[str] = []
    spans: list[Span] = []
    stack: list[tuple[str, int]] = []
    position = 0
    index = 0

    def append(value: str) -> None:
        nonlocal position
        output.append(value)
        position += utf16_len(value)

    while index < len(source):
        char = source[index]
        if char == "\\" and index + 1 < len(source) and source[index + 1] in "\\*_~|`":
            append(source[index + 1])
            index += 2
            continue
        if char == "`":
            marker = "```" if source.startswith("```", index) else "`"
            end = source.find(marker, index + len(marker))
            if end < 0:
                raise MarkupError(f"Не закрыт маркер {marker}")
            if stack:
                raise MarkupError("Код нельзя вкладывать в другое выделение")
            value = source[index + len(marker):end]
            if marker == "```" and "\n" in value:
                label, rest = value.split("\n", 1)
                if not label or (len(label) <= 24 and label.replace("-", "").isalnum()):
                    value = rest
            start = position
            append(value)
            if position > start:
                spans.append(Span("pre" if marker == "```" else "code", start, position - start))
            index = end + len(marker)
            continue
        marker = next((m for m in ("**", "__", "~~", "||", "_")
                       if source.startswith(m, index)), None)
        if marker == "_":
            # Leave identifiers, URLs and hashtags containing underscores alone.
            closing = bool(stack and stack[-1][0] == marker)
            before = source[index - 1] if index else ""
            after = source[index + 1] if index + 1 < len(source) else ""
            if (closing and after.isalnum()) or (not closing and before.isalnum()):
                marker = None
        if marker:
            if stack and stack[-1][0] == marker:
                _, start = stack.pop()
                if position > start:
                    spans.append(Span(markers[marker], start, position - start))
            elif any(item[0] == marker for item in stack):
                raise MarkupError("Выделения пересекаются. Закрывай их в обратном порядке")
            else:
                stack.append((marker, position))
            index += len(marker)
            continue
        append(char)
        index += 1
    if stack:
        raise MarkupError(f"Не закрыт маркер {stack[-1][0]}")
    text = "".join(output)
    if not text.strip():
        raise MarkupError("После удаления разметки текст пуст")
    return FormattedPost(text, tuple(sorted(spans, key=lambda e: (e.offset, -e.length, e.type))))


def split_post(post: FormattedPost, limit: int = 4096) -> list[FormattedPost]:
    """Split without dropping text, bisecting emoji or losing a spanning style."""
    if limit < 2:
        raise ValueError("limit must be at least 2")
    result = []
    start = 0
    unit_start = 0
    while start < len(post.text):
        end = start
        units = 0
        while end < len(post.text):
            size = 2 if ord(post.text[end]) > 0xFFFF else 1
            if units + size > limit:
                break
            units += size
            end += 1
        if end < len(post.text):
            newline = post.text.rfind("\n", start, end)
            if newline >= start + (end - start) // 2:
                end = newline + 1
                units = utf16_len(post.text[start:end])
        clipped = []
        for entity in post.entities:
            left = max(entity.offset, unit_start)
            right = min(entity.offset + entity.length, unit_start + units)
            if right > left:
                clipped.append(Span(entity.type, left - unit_start, right - left))
        if len(clipped) > 100:
            raise MarkupError("Слишком много выделений в одном сообщении (больше 100)")
        result.append(FormattedPost(post.text[start:end], tuple(clipped)))
        start = end
        unit_start += units
    return result
