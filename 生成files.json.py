from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
OUT_FILE = ROOT / "files.json"

def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    return (
        "node_modules" in parts
        or ".git" in parts
        or "__pycache__" in parts
        or path.name == "files.json"
    )

def main() -> None:
    files = []
    for p in ROOT.rglob("*.js"):
        if p.is_file() and not should_skip(p):
            files.append(p.relative_to(ROOT).as_posix())

    files.sort()

    with OUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(files, f, ensure_ascii=False, indent=2)

    print(f"已生成 {OUT_FILE.name}，共 {len(files)} 个 .js 文件")

if __name__ == "__main__":
    main()
