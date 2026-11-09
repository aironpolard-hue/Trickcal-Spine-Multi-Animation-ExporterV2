from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import types
from pathlib import Path, PurePosixPath
from typing import Any

# UnityPy exposes optional AudioClip helpers from its generated class package.
# This reader never touches audio, so provide a tiny stub before importing
# UnityPy instead of shipping the optional FMOD runtime.
if "fmod_toolkit" not in sys.modules:
    fmod_stub = types.ModuleType("fmod_toolkit")

    def unsupported_audio(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("Audio conversion is not available in the Spine reader")

    fmod_stub.raw_to_wav = unsupported_audio
    sys.modules["fmod_toolkit"] = fmod_stub

import UnityPy


CACHE_VERSION = 2


def object_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8", errors="surrogateescape")
    return bytes(value)


def is_unityfs(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(8) == b"UnityFS\x00"
    except OSError:
        return False


def find_text_asset(path: Path, expected_suffix: str) -> bytes:
    if not is_unityfs(path):
        return path.read_bytes()

    environment = UnityPy.load(str(path))
    matches: list[bytes] = []
    for reader in environment.objects:
        if reader.type.name != "TextAsset":
            continue
        data = reader.read()
        payload = object_bytes(data.m_Script)
        name = str(getattr(data, "m_Name", "") or "")
        if name.casefold().endswith(expected_suffix.casefold()):
            matches.append(payload)
    if len(matches) != 1:
        raise ValueError(
            f"Expected one {expected_suffix} TextAsset in {path.name}, found {len(matches)}"
        )
    return matches[0]


def split_field(line: str) -> tuple[str, str] | None:
    if ":" not in line:
        return None
    key, value = line.split(":", 1)
    return key.strip(), value.strip()


def parse_atlas_pages(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    pages: list[str] = []
    index = 0

    while index < len(lines) and not lines[index].strip():
        index += 1
    while index < len(lines):
        if split_field(lines[index]) is None:
            break
        index += 1

    while index < len(lines):
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines):
            break

        page_name = lines[index].strip()
        index += 1
        if not page_name:
            continue
        pages.append(page_name)

        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
                break
            if split_field(line) is None:
                break
            index += 1

        while index < len(lines):
            if not lines[index].strip():
                break
            index += 1
            while index < len(lines):
                line = lines[index]
                if not line.strip():
                    break
                if split_field(line) is None:
                    break
                index += 1
            if index < len(lines) and not lines[index].strip():
                break

    return pages


def file_signature(path: Path) -> list[int]:
    stat = path.stat()
    return [int(stat.st_size), int(stat.st_mtime_ns)]


def cache_key(folder: Path, atlas: Path, skeleton: Path) -> str:
    value = "\n".join(
        [
            str(folder.resolve()),
            str(atlas.resolve()),
            str(skeleton.resolve()),
        ]
    )
    return hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()[:32]


def cache_is_valid(target: Path) -> bool:
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if manifest.get("version") != CACHE_VERSION:
        return False

    for raw_path, expected in manifest.get("sources", {}).items():
        source = Path(raw_path)
        if not source.is_file():
            return False
        try:
            if file_signature(source) != expected:
                return False
        except OSError:
            return False

    return all((target / relative).is_file() for relative in manifest.get("outputs", []))


def safe_page_path(target: Path, page_name: str) -> Path:
    relative = PurePosixPath(page_name.replace("\\", "/"))
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"Unsafe Atlas page path: {page_name}")
    result = target.joinpath(*relative.parts)
    result.parent.mkdir(parents=True, exist_ok=True)
    return result


def load_texture(path: Path) -> Any:
    if path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
        from PIL import Image

        return Image.open(path).convert("RGBA")

    if not is_unityfs(path):
        raise ValueError(f"Unsupported texture source: {path.name}")
    environment = UnityPy.load(str(path))
    for reader in environment.objects:
        if reader.type.name == "Texture2D":
            return reader.read().image
    raise ValueError(f"No Texture2D found in {path.name}")


def texture_source_map(folder: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for child in folder.iterdir():
        if not child.is_file():
            continue
        result[child.name.casefold()] = child
    return result


def resolve_texture_sources(folder: Path, pages: list[str]) -> list[tuple[str, Path]]:
    children = texture_source_map(folder)
    resolved: list[tuple[str, Path]] = []
    missing: list[str] = []

    for page in pages:
        page_path = PurePosixPath(page.replace("\\", "/"))
        stem = page_path.stem.casefold()
        candidate = children.get(stem)
        if candidate is None:
            candidate = children.get(page.casefold())
        if candidate is None:
            missing.append(page)
        else:
            resolved.append((page, candidate))

    if not missing:
        return resolved

    # The current game build uses exact page stems as bundle file names. This
    # fallback also handles future builds that only preserve Texture2D names.
    for page in missing:
        page_stem = PurePosixPath(page.replace("\\", "/")).stem.casefold()
        found: Path | None = None
        for candidate in folder.iterdir():
            if not candidate.is_file() or candidate.suffix:
                continue
            try:
                environment = UnityPy.load(str(candidate))
                for reader in environment.objects:
                    if reader.type.name != "Texture2D":
                        continue
                    data = reader.read()
                    name = str(getattr(data, "m_Name", "") or "").casefold()
                    if name == page_stem:
                        found = candidate
                        break
                if found is not None:
                    break
            except Exception:
                continue
        if found is None:
            raise FileNotFoundError(f"Texture2D bundle not found for Atlas page {page}")
        resolved.append((page, found))

    return resolved


def prepare(folder: Path, atlas_path: Path, skeleton_path: Path, cache_root: Path) -> Path:
    folder = folder.resolve()
    atlas_path = atlas_path.resolve()
    skeleton_path = skeleton_path.resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    target = cache_root / cache_key(folder, atlas_path, skeleton_path)

    if cache_is_valid(target):
        return target
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    atlas_payload = find_text_asset(atlas_path, ".atlas")
    skeleton_payload = find_text_asset(skeleton_path, ".skel")
    skeleton_payload = patch_null_skeleton_header_strings(skeleton_payload)
    atlas_text = atlas_payload.decode("utf-8-sig")
    pages = parse_atlas_pages(atlas_text)
    if not pages:
        raise ValueError(f"Atlas has no pages: {atlas_path.name}")

    texture_sources = resolve_texture_sources(folder, pages)
    atlas_output = target / atlas_path.name
    skeleton_output = target / skeleton_path.name
    atlas_output.write_bytes(atlas_payload)
    skeleton_output.write_bytes(skeleton_payload)

    outputs = [atlas_output.relative_to(target).as_posix(), skeleton_output.relative_to(target).as_posix()]
    sources: dict[str, list[int]] = {
        str(atlas_path): file_signature(atlas_path),
        str(skeleton_path): file_signature(skeleton_path),
    }
    for page, source in texture_sources:
        output = safe_page_path(target, page)
        image = load_texture(source)
        image.save(output, format="PNG")
        outputs.append(output.relative_to(target).as_posix())
        sources[str(source.resolve())] = file_signature(source)

    manifest = {
        "version": CACHE_VERSION,
        "folder": str(folder),
        "atlas": str(atlas_path),
        "skeleton": str(skeleton_path),
        "sources": sources,
        "outputs": outputs,
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    return target


def server_main() -> int:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request_id: Any = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            target = prepare(
                Path(request["folder"]),
                Path(request["atlas"]),
                Path(request["skeleton"]),
                Path(request["cache_root"]),
            )
            response = {"id": request_id, "ok": True, "target": str(target)}
        except Exception as error:
            response = {
                "id": request_id,
                "ok": False,
                "error_type": type(error).__name__,
                "error": str(error),
            }
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        return server_main()
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("atlas", type=Path)
    parser.add_argument("skeleton", type=Path)
    parser.add_argument("cache_root", type=Path)
    parser.add_argument("result_file", type=Path, nargs="?")
    args = parser.parse_args()

    def emit(message: str) -> None:
        if args.result_file is None:
            print(message, flush=True)
            return
        args.result_file.parent.mkdir(parents=True, exist_ok=True)
        args.result_file.write_text(message + "\n", encoding="utf-8", newline="\n")

    try:
        target = prepare(args.folder, args.atlas, args.skeleton, args.cache_root)
        emit(f"READY\t{target}")
        return 0
    except Exception as error:
        emit(f"ERROR\t{type(error).__name__}\t{error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())


def _read_header_varint(data: bytes, pos: int):
    value = 0
    shift = 0
    for _ in range(5):
        if pos >= len(data):
            return None
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, pos
        shift += 7
    return None


def _collect_null_header_string(data: bytes, pos: int, positions: list[int]) -> int:
    parsed = _read_header_varint(data, pos)
    if parsed is None:
        return -1
    value, content_start = parsed
    if value == 0:
        positions.append(pos)
        return content_start
    end = content_start + value - 1
    if end < 0 or end > len(data):
        return -1
    return end


def patch_null_skeleton_header_strings(data: bytes) -> bytes:
    """Rewrite null header strings (version/imagesPath/audioPath) to empty strings.

    Some game bundles encode these as length 0x00. spine-c then calls
    strlen(NULL) while reading the header, which crashes. Changing the length
    byte to 0x01 makes the parser read an empty string without consuming bytes.
    """
    if not data:
        return data
    try:
        positions: list[int] = []
        pos = 8  # hash
        pos = _collect_null_header_string(data, pos, positions)
        if pos < 0 or pos + 16 > len(data):
            return _apply_header_patch(data, positions)
        pos += 16  # x, y, width, height
        if pos >= len(data):
            return _apply_header_patch(data, positions)
        nonessential = data[pos] != 0
        pos += 1
        if not nonessential:
            return _apply_header_patch(data, positions)
        if pos + 4 > len(data):
            return _apply_header_patch(data, positions)
        pos += 4  # fps
        pos = _collect_null_header_string(data, pos, positions)
        if pos < 0:
            return _apply_header_patch(data, positions)
        pos = _collect_null_header_string(data, pos, positions)
        if pos < 0:
            return _apply_header_patch(data, positions)
        return _apply_header_patch(data, positions)
    except Exception:
        return data


def _apply_header_patch(data: bytes, positions: list[int]) -> bytes:
    if not positions:
        return data
    result = bytearray(data)
    for position in positions:
        if 0 <= position < len(result) and result[position] == 0:
            result[position] = 1
    return bytes(result)
