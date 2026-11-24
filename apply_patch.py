#!/usr/bin/env python3
"""
Автоматический раскладчик патчей из .md файла по папкам проекта.
Использование:
    python apply_patch.py              # читает patch.md
    python apply_patch.py my_fix.md    # читает указанный .md
    python apply_patch.py --dry-run    # только показать, что изменится
"""
import os
import re
import sys
from pathlib import Path

HEADER_RE = re.compile(r"^#{2,6}\s+`([^`\r\n]+)`")
FENCE_RE = re.compile(r"^(`{3,})(.*)$")
KNOWN_NO_EXT = {"Dockerfile", "Makefile", "v", "d"}


def _is_valid_rel_path(raw: str) -> bool:
    p = raw.strip().replace("\\", "/")
    if not p or p.startswith("/") or ".." in p.split("/") or " " in p:
        return False
    return ("/" in p) or ("." in p) or (p in KNOWN_NO_EXT)


def parse_markdown_patch(md_text: str) -> list[tuple[str, str]]:
    lines = md_text.splitlines(keepends=True)
    results: list[tuple[str, str]] = []

    pending_path: str | None = None
    in_code = False
    fence_len = 0
    buf: list[str] = []

    for line in lines:
        stripped = line.rstrip("\r\n")

        if not in_code:
            m_hdr = HEADER_RE.match(stripped)
            if m_hdr:
                cand = m_hdr.group(1).strip().replace("\\", "/")
                pending_path = cand if _is_valid_rel_path(cand) else None
                continue

            if pending_path is not None:
                m_fence = FENCE_RE.match(stripped)
                if m_fence:
                    in_code = True
                    fence_len = len(m_fence.group(1))
                    buf = []
                    continue
                if stripped.startswith("#"):
                    pending_path = None
        else:
            m_end = FENCE_RE.match(stripped)
            if m_end and len(m_end.group(1)) >= fence_len and not m_end.group(2).strip():
                results.append((pending_path, "".join(buf)))
                pending_path = None
                in_code = False
                fence_len = 0
                buf = []
            else:
                buf.append(line)

    return results


def apply_files(root: Path, files: list[tuple[str, str]], dry_run: bool = False) -> None:
    if not files:
        print("⚠️ В .md файле не найдено блоков кода под заголовками вида: #### `path/to/file`")
        return

    root_resolved = root.resolve()
    applied = 0

    for rel_str, content in files:
        target = (root_resolved / rel_str).resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError:
            print(f"❌ Пропущен небезопасный путь: {rel_str}")
            continue

        tag = "UPD" if target.exists() else "NEW"
        line_cnt = content.count("\n") + (0 if content.endswith("\n") or not content else 1)

        if dry_run:
            print(f"[DRY {tag}] {rel_str} ({line_cnt} строк)")
            applied += 1
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp_patch")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)
        print(f"[{tag}] {rel_str} ({line_cnt} строк)")
        applied += 1

    print(f"\n✅ Готово! Обработано файлов: {applied}")


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    md_args = [a for a in args if not a.startswith("-")]
    patch_file = Path(md_args[0]) if md_args else Path("patch.md")

    if not patch_file.is_file():
        print(f"❌ Файл '{patch_file}' не найден. Создай patch.md и вставь туда ответ с кодом.")
        sys.exit(1)

    text = patch_file.read_text(encoding="utf-8", errors="replace")
    parsed = parse_markdown_patch(text)
    apply_files(Path.cwd(), parsed, dry_run=dry_run)


if __name__ == "__main__":
    main()