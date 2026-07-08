#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量上传文件到 GitHub Release（支持手动选择文件，中文文件名完整保留）
依赖：GitHub CLI (gh)，需提前登录：gh auth login

上传使用 gh release upload "路径#显示名" 语法，
与 PowerShell 的 "$($_.FullName)#$($_.Name)" 完全一致，
确保中文文件名在 Release 页面上正确显示。
"""

import os
import sys
import re
import json
import subprocess
import urllib.parse

# ── 控制台 UTF-8（Windows PowerShell 适配）──────────────────────────────────
if sys.platform == "win32":
    import ctypes
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    ctypes.windll.kernel32.SetConsoleCP(65001)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 颜色输出（Windows 兼容）──────────────────────────────────────────────────
def supports_color():
    return sys.platform != "win32" or os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM")

USE_COLOR = supports_color()

def c(text, code):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

def green(t):  return c(t, "32")
def red(t):    return c(t, "31")
def yellow(t): return c(t, "33")
def cyan(t):   return c(t, "36")
def bold(t):   return c(t, "1")

def hr(char="─", width=60):
    print(char * width)

# ── 工具函数 ─────────────────────────────────────────────────────────────────

def run(cmd: list[str], check=True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )

def gh(*args, **kwargs) -> str:
    result = run(["gh", *args], **kwargs)
    return result.stdout.strip()

def choose_one(prompt: str, options: list[str]) -> str:
    if not options:
        print(red("❌ 列表为空，无法选择。"))
        sys.exit(1)

    print(f"\n{bold(prompt)}")
    for i, opt in enumerate(options, 1):
        print(f"  {cyan(f'[{i:>3}]')} {opt}")

    while True:
        raw = input("\n请输入序号：").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print(yellow(f"  ⚠️  请输入 1 ~ {len(options)} 之间的数字"))


def pick_files() -> list[str]:
    print(f"\n{bold('📂 正在打开文件选择框……')}")
    print(f"  {cyan('提示')}：按住 Ctrl 可多选文件，按住 Shift 可范围选择\n")

    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print(red("❌ 当前环境缺少 tkinter，无法弹出文件选择框。"))
        print(yellow("   Linux 请安装：sudo apt install python3-tk"))
        sys.exit(1)

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    chosen = filedialog.askopenfilenames(title="选择要上传的文件（可多选）", parent=root)
    root.destroy()
    chosen = list(chosen)

    if not chosen:
        print(yellow("  ⚠️  未选择任何文件。"))
        return []

    print(green(f"  ✅ 已选择 {len(chosen)} 个文件："))
    for f in chosen:
        print(f"    • {os.path.basename(f)}  {yellow(_human_size(os.path.getsize(f)))}")

    return chosen


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ── 全中文文件名检测与重命名 ──────────────────────────────────────────────────

def _is_all_chinese_stem(stem: str) -> bool:
    """主干仅含中文（无任何 ASCII 字母或数字）则返回 True。"""
    if not stem:
        return False
    has_chinese = bool(re.search(r'[\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002a6df]', stem))
    has_ascii_alnum = bool(re.search(r'[A-Za-z0-9]', stem))
    return has_chinese and not has_ascii_alnum


def rename_all_chinese_files(file_paths: list[str]) -> list[str]:
    """
    找出纯中文主干的文件，末尾追加三位编号（001、002……）并直接重命名。
    返回更新后的路径列表。
    """
    to_rename = [p for p in file_paths
                 if _is_all_chinese_stem(os.path.splitext(os.path.basename(p))[0])]

    if not to_rename:
        return file_paths

    print()
    hr()
    print(bold("🔍 检测到纯中文文件名，将自动追加编号"))
    hr()
    print(f"  {cyan('说明')}：文件名主干不含任何英文字母/数字的文件将被重命名")
    print(f"         例：批图.png  →  批图001.png\n")

    counter = 1
    updated_paths = list(file_paths)

    for orig_path in to_rename:
        directory = os.path.dirname(orig_path)
        basename  = os.path.basename(orig_path)
        stem, ext = os.path.splitext(basename)

        while True:
            new_name = f"{stem}{counter:03d}{ext}"
            new_path = os.path.join(directory, new_name)
            if not os.path.exists(new_path) or new_path == orig_path:
                break
            counter += 1

        try:
            os.rename(orig_path, new_path)
            idx = updated_paths.index(orig_path)
            updated_paths[idx] = new_path
            print(f"  {yellow('✏️  重命名')}：{basename}  →  {green(new_name)}")
        except OSError as e:
            print(red(f"  ❌ 重命名失败：{basename}  原因：{e}"))

        counter += 1

    hr()
    return updated_paths


# ── 确认上传 ─────────────────────────────────────────────────────────────────

def confirm_upload(chosen: list[str], repo: str, tag: str) -> bool:
    print()
    hr()
    print(bold("📋 上传确认"))
    hr()
    print(f"  目标仓库：{cyan(repo)}")
    print(f"  Release ：{cyan(tag)}")
    print(f"  文件数量：{cyan(str(len(chosen)))} 个")
    print()
    print(bold("  待上传文件："))
    total_size = 0
    for f in chosen:
        size = os.path.getsize(f)
        total_size += size
        print(f"    • {os.path.basename(f)}  {yellow(_human_size(size))}")
    print(f"\n  合计大小：{yellow(_human_size(total_size))}")
    hr()
    ans = input("\n确认上传以上文件？(y/n): ").strip().lower()
    return ans == "y"


# ── 核心上传：gh release upload "路径#显示名" ─────────────────────────────────

def upload_asset_gh(filepath: str, repo: str, tag: str) -> str:
    """
    使用 gh release upload 的 "路径#显示名" 语法上传文件。

    等价于 PowerShell：
        gh release upload <tag> "$($_.FullName)#$($_.Name)" -R <repo> --clobber

    # 号后面是 label（Release 页面显示名），gh CLI 原生支持 UTF-8，
    中文文件名直接传入，无需任何编码处理。

    返回文件的标准下载 URL。
    """
    filename = os.path.basename(filepath)
    # "绝对路径#文件名"  ——  # 后即为 Release 页面上的显示标签
    asset_spec = f"{filepath}#{filename}"

    result = subprocess.run(
        ["gh", "release", "upload", tag, asset_spec,
         "--repo", repo, "--clobber"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())

    # 拼接标准下载 URL
    encoded_tag  = urllib.parse.quote(tag,      safe="")
    encoded_name = urllib.parse.quote(filename, safe="")
    return f"https://github.com/{repo}/releases/download/{encoded_tag}/{encoded_name}"


# ── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    hr("═")
    print(bold("   🚀 GitHub Release 批量上传工具"))
    hr("═")

    # 1. 检查 gh
    print("\n⏳ 检查 GitHub CLI……")
    try:
        ver = run(["gh", "--version"]).stdout.split("\n")[0].strip()
        print(green(f"  ✅ {ver}"))
    except FileNotFoundError:
        print(red("❌ 未找到 GitHub CLI，请先安装并登录：https://cli.github.com/"))
        sys.exit(1)

    # 2. 登录状态
    print("⏳ 检查登录状态……")
    try:
        user = gh("api", "user", "--jq", ".login")
        print(green(f"  ✅ 已登录账号：{user}"))
    except subprocess.CalledProcessError:
        print(red("❌ 未登录 GitHub CLI，请先运行：gh auth login"))
        sys.exit(1)

    # 3. 获取仓库列表
    print("\n⏳ 正在获取仓库列表……")
    try:
        repos_json = gh("repo", "list", "--limit", "100", "--json", "nameWithOwner")
        repos = [r["nameWithOwner"] for r in json.loads(repos_json)]
        print(green(f"  ✅ 共找到 {len(repos)} 个仓库"))
    except Exception as e:
        print(red(f"❌ 获取仓库列表失败：{e}"))
        sys.exit(1)

    repo = choose_one("请选择目标仓库：", repos)
    print(green(f"\n  ✅ 已选择仓库：{repo}"))

    # 4. 获取 Release 标签
    print("\n⏳ 正在获取 Release 标签列表……")
    try:
        tags_json = gh("release", "list", "--repo", repo, "--limit", "50", "--json", "tagName")
        tags = [r["tagName"] for r in json.loads(tags_json)]
        print(green(f"  ✅ 共找到 {len(tags)} 个 Release"))
    except Exception as e:
        print(red(f"❌ 获取 Release 列表失败：{e}"))
        sys.exit(1)

    if not tags:
        print(red("❌ 该仓库没有任何 Release，请先在 GitHub 上创建 Release。"))
        sys.exit(1)

    tag = choose_one("请选择 Release 标签：", tags)
    print(green(f"\n  ✅ 已选择标签：{tag}"))

    # 5. 弹出文件选择框
    chosen_abs = pick_files()
    while not chosen_abs:
        retry = input("\n未选择文件，是否重新选择？(y/n): ").strip().lower()
        if retry != "y":
            print(yellow("已取消。"))
            _pause()
            sys.exit(0)
        chosen_abs = pick_files()

    # 6. 检查并重命名纯中文文件名
    chosen_abs = rename_all_chinese_files(chosen_abs)

    # 7. 确认上传
    if not confirm_upload(chosen_abs, repo, tag):
        print(yellow("\n已取消上传。"))
        _pause()
        sys.exit(0)

    # 8. 逐个上传
    print()
    hr()
    print(bold(f"🚀 开始上传，共 {len(chosen_abs)} 个文件……"))
    print(f"  {cyan('说明')}：使用 gh CLI \"路径#显示名\" 语法，中文文件名完整保留")
    hr()
    success, failed = [], []

    for idx, filepath in enumerate(chosen_abs, 1):
        filename = os.path.basename(filepath)
        size_str = _human_size(os.path.getsize(filepath))
        print(f"\n[{idx}/{len(chosen_abs)}] {bold(filename)}  {yellow(size_str)}")

        try:
            print(f"  ⬆️  上传中……", end="", flush=True)
            download_url = upload_asset_gh(filepath, repo, tag)
            print("\r" + green(f"  ✅ 上传成功：{filename}"))
            if download_url:
                print(f"     🔗 {cyan(download_url)}")
            success.append(filename)

        except Exception as e:
            err = str(e).strip()
            print("\r" + red(f"  ❌ 上传失败：{filename}"))
            print(red(f"     错误信息：{err}"))
            failed.append((filename, err))

    # 9. 汇总报告
    print()
    hr("═")
    print(bold("📊 上传结果汇总"))
    hr("═")
    total = len(chosen_abs)
    print(f"  总计文件：{cyan(str(total))} 个")
    print(green(f"  上传成功：{len(success)} 个"))
    print((red if failed else green)(f"  上传失败：{len(failed)} 个"))

    if success:
        print(f"\n  {green('✅ 成功列表：')}")
        for f in success:
            print(f"    • {f}")

    if failed:
        print(f"\n  {red('❌ 失败列表：')}")
        for f, err in failed:
            print(f"    • {f}")
            print(red(f"      原因：{err}"))

    print()
    release_url = f"https://github.com/{repo}/releases/tag/{tag}"
    print(f"  🔗 Release 页面：{cyan(release_url)}")
    hr("═")

    _pause()


def _pause():
    print()
    try:
        input("按 Enter 键退出……")
    except EOFError:
        pass


if __name__ == "__main__":
    main()
