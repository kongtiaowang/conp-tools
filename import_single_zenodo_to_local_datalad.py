#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import urllib.request
from typing import List, Dict, Any

TEXT_EXTENSIONS = {'.csv', '.json', '.md', '.txt', '.py', '.yml', '.yaml'}

def run(cmd: list[str], cwd: str | None = None):
    subprocess.run(cmd, cwd=cwd, check=True)

def clean_title(title: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*]', '_', title)
    clean = re.sub(r'\s+', '_', clean)
    clean = re.sub(r'_+', '_', clean)
    clean = clean.strip('_')
    if len(clean) > 80:
        clean = clean[:80].strip('_')
    return clean

def download_file_to_disk(url: str, dest_path: str, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as response, open(dest_path, "wb") as out_file:
        out_file.write(response.read())

def configure_git_attributes(dataset_dir: str):
    """
    配置 .gitattributes。
    使用 'expression' 语法：(anything) 表示匹配，'nothing' 表示不匹配。
    """
    attr_path = os.path.join(dataset_dir, ".gitattributes")
    # 修正语法：annex.largefiles 后面跟的是表达式
    # 'nothing' 是 git-annex 识别的合法表达式，表示没有任何文件属于大文件
    patterns = [
        "README.md annex.largefiles=nothing",
        "DATS.json annex.largefiles=nothing",
        ".conp-zenodo-crawler.json annex.largefiles=nothing",
        "*.csv annex.largefiles=nothing",
        "*.json annex.largefiles=nothing",
        "*.txt annex.largefiles=nothing",
        ".gitattributes annex.largefiles=nothing"
    ]
    with open(attr_path, "w") as f:
        f.write("\n".join(patterns) + "\n")
    # 先用 git add 保护这个属性文件
    run(["git", "add", ".gitattributes"], cwd=dataset_dir)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", required=True)
    parser.add_argument("--basedir", default=".")
    parser.add_argument("--config", default=os.path.expanduser("~/.conp_crawler_config.json"))
    parser.add_argument("--zenodo-token")
    args = parser.parse_args()

    record_id = args.record.split("/")[-1]
    # 尝试多种方式获取 token
    token = os.getenv("ZENODO_TOKEN") or os.getenv("DATALAD_ZENODO_token")
    
    print(f"📥 Fetching Zenodo record {record_id}...")
    # 这里直接用简洁的获取方式
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(f"https://zenodo.org/api/records/{record_id}", headers=headers)
    with urllib.request.urlopen(req) as r:
        record = json.loads(r.read().decode())
    
    title = record.get("metadata", {}).get("title", f"Record_{record_id}")
    dataset_dir = os.path.abspath(os.path.join(args.basedir, "projects", clean_title(title)))
    print(f"📂 Preparing directory: {dataset_dir}")
    os.makedirs(dataset_dir, exist_ok=True)

    print("🚀 Initializing DataLad...")
    run(["datalad", "create", "--force", "."], cwd=dataset_dir)
    configure_git_attributes(dataset_dir)

    files = record.get("files", [])
    for f_item in files:
        name = f_item["key"]
        url = f_item["links"]["self"]
        ext = os.path.splitext(name)[1].lower()
        dest = os.path.join(dataset_dir, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        if ext in TEXT_EXTENSIONS:
            print(f"   📄 [TEXT] Downloading: {name}")
            download_file_to_disk(url, dest, token)
            # 使用普通的 git add
            run(["git", "add", name], cwd=dataset_dir)
        else:
            print(f"   📦 [LARGE] Adding Link: {name}")
            # 使用 relaxed 模式注册大文件
            run(["git", "annex", "addurl", url, "--fast", "--relaxed", "--file", name], cwd=dataset_dir)

    print("💾 Saving dataset state...")
    # 保存时，DataLad 会遵循 .gitattributes 的规则
    run(["datalad", "save", "-m", f"Import Zenodo {record_id} with mixed storage mode"], cwd=dataset_dir)
    print(f"\n✅ Success! Dataset ready at {dataset_dir}")

if __name__ == "__main__":
    main()
