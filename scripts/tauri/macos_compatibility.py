"""Check the actual deployment target of an arm64 app and its frozen runtime."""

from __future__ import annotations

import argparse
from pathlib import Path
import struct

ARM64 = 0x0100000C
DEFAULT_MAXIMUM = (14, 0, 0)
THIN_MAGIC = {b"\xcf\xfa\xed\xfe": "<", b"\xfe\xed\xfa\xcf": ">"}
FAT_MAGIC = {
    b"\xca\xfe\xba\xbe": (">", False),
    b"\xbe\xba\xfe\xca": ("<", False),
    b"\xca\xfe\xba\xbf": (">", True),
    b"\xbf\xba\xfe\xca": ("<", True),
}


def version_string(version: tuple[int, int, int]) -> str:
    return ".".join(map(str, version))


def parse_version(value: str) -> tuple[int, int, int]:
    parts = tuple(map(int, value.split(".")))
    if not 1 <= len(parts) <= 3 or any(part < 0 for part in parts):
        raise ValueError(f"Invalid macOS version: {value}")
    return (parts + (0, 0))[:3]


def _unpack_version(value: int) -> tuple[int, int, int]:
    return value >> 16, (value >> 8) & 255, value & 255


def macho_targets(data: bytes) -> list[tuple[int, tuple[int, int, int] | None]]:
    """Return CPU/minimum-macOS pairs; SDK version is deliberately not used."""
    magic = data[:4]
    if magic in FAT_MAGIC:
        endian, wide = FAT_MAGIC[magic]
        if len(data) < 8:
            raise ValueError("Truncated universal Mach-O header")
        count = struct.unpack_from(endian + "I", data, 4)[0]
        record_size = 32 if wide else 20
        if count > (len(data) - 8) // record_size:
            raise ValueError("Truncated universal Mach-O architecture table")
        targets = []
        for index in range(count):
            entry = 8 + index * record_size
            offset, size = struct.unpack_from(endian + ("QQ" if wide else "II"), data, entry + 8)
            if offset < 8 + count * record_size or size > len(data) - offset:
                raise ValueError("Invalid universal Mach-O slice")
            targets.extend(macho_targets(data[offset:offset + size]))
        return targets
    if magic not in THIN_MAGIC:
        return []
    if len(data) < 32:
        raise ValueError("Truncated Mach-O header")
    endian = THIN_MAGIC[magic]
    cpu = struct.unpack_from(endian + "I", data, 4)[0]
    count, command_bytes = struct.unpack_from(endian + "II", data, 16)
    end = 32 + command_bytes
    if end > len(data):
        raise ValueError("Truncated Mach-O load commands")
    position = 32
    minimum = None
    for _ in range(count):
        if position + 8 > end:
            raise ValueError("Truncated Mach-O load command")
        command, size = struct.unpack_from(endian + "II", data, position)
        if size < 8 or position + size > end:
            raise ValueError("Invalid Mach-O load command length")
        if command == 0x32:  # LC_BUILD_VERSION
            if size < 24:
                raise ValueError("Truncated LC_BUILD_VERSION")
            platform, value = struct.unpack_from(endian + "II", data, position + 8)
            if platform != 1:
                raise ValueError(f"Mach-O targets Apple platform {platform}, not macOS")
            candidate = _unpack_version(value)
            minimum = max(minimum or candidate, candidate)
        elif command == 0x24:  # LC_VERSION_MIN_MACOSX
            if size < 16:
                raise ValueError("Truncated LC_VERSION_MIN_MACOSX")
            candidate = _unpack_version(struct.unpack_from(endian + "I", data, position + 8)[0])
            minimum = max(minimum or candidate, candidate)
        position += size
    if position != end:
        raise ValueError("Mach-O load command size does not match its header")
    return [(cpu, minimum)]


def check_macho(data: bytes, label: str, maximum=DEFAULT_MAXIMUM, *, require_arm64=False) -> int:
    targets = [minimum for cpu, minimum in macho_targets(data) if cpu == ARM64]
    if require_arm64 and not targets:
        raise ValueError(f"{label}: no arm64 Mach-O binary")
    for minimum in targets:
        if minimum is None:
            raise ValueError(f"{label}: missing macOS deployment target")
        if minimum > maximum:
            raise ValueError(
                f"{label}: requires macOS {version_string(minimum)}; "
                f"supported minimum is {version_string(maximum)}"
            )
    return len(targets)


def check_file(path: Path, maximum=DEFAULT_MAXIMUM, *, require_arm64=False) -> int:
    # Only the Mach-O header/commands are needed for a thin executable, even
    # when a large PyInstaller archive is appended to it.
    with path.open("rb") as handle:
        header = handle.read(32)
        if header[:4] in THIN_MAGIC and len(header) == 32:
            endian = THIN_MAGIC[header[:4]]
            command_bytes = struct.unpack_from(endian + "I", header, 20)[0]
            if command_bytes > 16 * 1024 * 1024:
                raise ValueError(f"{path}: unreasonable Mach-O load command size")
            data = header + handle.read(command_bytes)
        elif header[:4] in FAT_MAGIC:
            handle.seek(0)
            data = handle.read()
        else:
            data = header
    return check_macho(data, str(path), maximum, require_arm64=require_arm64)


def check_runtime(runtime: Path, maximum=DEFAULT_MAXIMUM) -> int:
    from PyInstaller.archive.readers import CArchiveReader

    count = check_file(runtime, maximum, require_arm64=True)
    archive = CArchiveReader(str(runtime))
    embedded = 0
    for name, entry in archive.toc.items():
        # The archive TOC marks collected native binaries with 'b'. Also
        # inspect dylibs/extensions explicitly copied as data by a hook.
        if (
            entry[-1] != "b"
            and not name.endswith((".dylib", ".so"))
            and Path(name).name not in {"uv", "ruff"}
        ):
            continue
        native_count = check_macho(archive.extract(name), f"{runtime.name}!{name}", maximum)
        count += native_count
        embedded += native_count
    if not embedded:
        raise ValueError(f"{runtime}: no embedded arm64 binaries found")
    return count


def check_bundle(bundle: Path, maximum=DEFAULT_MAXIMUM) -> int:
    if not bundle.is_dir() or bundle.suffix != ".app":
        raise ValueError(f"Not an application bundle: {bundle}")
    count = 0
    for path in bundle.rglob("*"):
        if path.is_file() and not path.is_symlink():
            count += check_file(path, maximum)
    if not count:
        raise ValueError(f"{bundle}: no arm64 binaries found")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maximum", default="14.0", type=parse_version)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    count = check_runtime(args.runtime, args.maximum)
    if args.bundle:
        count += check_bundle(args.bundle, args.maximum)
    print(f"Verified {count} arm64 Mach-O slices for macOS {version_string(args.maximum)} compatibility")


if __name__ == "__main__":
    main()
