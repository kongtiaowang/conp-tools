#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import urllib.request
from typing import List, Dict, Any

# 定义需要直接保存为普通文件的后缀
TEXT_EXTENSIONS = {'.csv', '.json', '.md', '.txt', '.py', '.yml', '.yaml', '.tsv', '.jsonld', '.html'}
TEXT_FILENAMES = {'README', 'LICENSE', 'CHANGES', 'AUTHORS', 'MANIFEST', 'DESCRIPTION'}

def is_text_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    base = os.path.basename(filename).upper()
    return ext in TEXT_EXTENSIONS or base in TEXT_FILENAMES

def run(cmd: list[str], cwd: str | None = None):
    subprocess.run(cmd, cwd=cwd, check=True)

def clean_title(title: str) -> str:
    """标题安全化，限制在 80 字符，并移除 Shell 不安全字符"""
    clean = title.replace('&', 'and')
    clean = re.sub(r'[<>:"/\\|?*(),]', '_', clean)
    clean = re.sub(r'\s+', '_', clean)
    clean = re.sub(r'_+', '_', clean)
    clean = clean.strip('_')
    if len(clean) > 80:
        clean = clean[:80].strip('_')
    return clean

def html_to_text(value: str) -> str:
    if not value: return ""
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()

def natural_size(num_bytes: int) -> tuple[float, str]:
    units = ["Bytes", "KB", "MB", "GB", "TB", "PB"]
    size = float(num_bytes)
    unit = units[0]
    for u in units:
        unit = u
        if size < 1024:
            break
        size /= 1024
    return (round(size, 2), unit)

def download_file_to_disk(url: str, dest_path: str, token: str | None = None):
    """将文件直接下载到本地磁盘"""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as response, open(dest_path, "wb") as out_file:
        out_file.write(response.read())

def configure_git_attributes(dataset_dir: str):
    """配置 .gitattributes 确保文本文件不进 Annex"""
    attr_path = os.path.join(dataset_dir, ".gitattributes")
    # 使用 nothing 语法修复之前的 Parse error
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
    run(["git", "add", ".gitattributes"], cwd=dataset_dir)

def generate_readme(record: dict, total_size: float, size_unit: str) -> str:
    metadata = record.get("metadata", {})
    return f"""# {metadata.get('title')}

## Description
{html_to_text(metadata.get('description', 'No description provided.'))}

## Metadata
- **Zenodo Record ID**: {record.get('id')}
- **DOI**: {metadata.get('doi', 'N/A')}
- **Total Size**: {total_size} {size_unit}
- **Keywords**: {", ".join(metadata.get('keywords', []))}

---
*Automatically imported via CONP-Zenodo-Crawler*
"""

def generate_dats_json(record: dict, total_size: float, size_unit: str, file_count: int) -> dict:
    metadata = record.get("metadata", {})
    return {
        "title": metadata.get("title"),
        "description": html_to_text(metadata.get("description")),
        "creators": [{"name": c.get("name")} for c in metadata.get("creators", [])],
        "version": metadata.get("version", "1.0.0"),
        "types": [{"information": {"value": "dataset"}}],
        "licenses": [{"name": metadata.get("license", "None")}],
        "keywords": [{"value": k} for k in metadata.get("keywords", [])] if metadata.get("keywords") else [{"value": "N/A"}],
        "distributions": [{
            "size": total_size,
            "unit": {"value": size_unit},
            "access": {"landingPage": f"https://zenodo.org/record/{record.get('id')}"},
            "formats": ["N/A"]
        }],
        "extraProperties": [
            {"category": "source", "values": [{"value": "zenodo"}]},
            {"category": "zenodo_record_id", "values": [{"value": str(record.get('id'))}]},
            {"category": "files", "values": [{"value": str(file_count)}]},
            {"category": "subjects", "values": [{"value": "N/A"}]},
            {"category": "CONP_status", "values": [{"value": "CONP"}]}
        ]
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", required=True)
    parser.add_argument("--basedir", default=".")
    parser.add_argument("--zenodo-token")
    args = parser.parse_args()

    record_id = args.record.split("/")[-1]
    token = args.zenodo_token or os.getenv("ZENODO_TOKEN") or os.getenv("DATALAD_ZENODO_token")

    print(f"📥 Fetching Zenodo record {record_id}...")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(f"https://zenodo.org/api/records/{record_id}", headers=headers)
    with urllib.request.urlopen(req) as r:
        record = json.loads(r.read().decode())
    
    title = record.get("metadata", {}).get("title", f"Record_{record_id}")
    folder_name = clean_title(title)
    dataset_dir = os.path.abspath(os.path.join(args.basedir, "projects", folder_name))
    print(f"📂 Preparing directory: {dataset_dir}")
    os.makedirs(dataset_dir, exist_ok=True)

    print("🚀 Initializing DataLad...")
    run(["datalad", "create", "--force", "."], cwd=dataset_dir)
    configure_git_attributes(dataset_dir)

    files = record.get("files", [])
    total_bytes = sum([int(f.get("size", 0)) for f in files])
    total_size, size_unit = natural_size(total_bytes)

    # 跟踪是否已经处理了元数据文件
    has_readme = False
    has_dats = False

    print(f"🔗 Processing {len(files)} files...")
    for f_item in files:
        name = f_item["key"]
        url = f_item["links"]["self"]
        ext = os.path.splitext(name)[1].lower()
        dest = os.path.join(dataset_dir, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        if name.lower() == "readme.md": has_readme = True
        if name.lower() == "dats.json": has_dats = True

        if is_text_file(name):
            print(f"   📄 [TEXT] Downloading: {name}")
            # 🌟 修复：如果文件已存在（可能是 Annex 链接），先删除它，否则 open() 会报错
            if os.path.lexists(dest):
                os.remove(dest)
            download_file_to_disk(url, dest, token)
            run(["git", "add", name], cwd=dataset_dir)
        else:
            print(f"   📦 [LARGE] Adding Link: {name}")
            run(["git", "annex", "addurl", url, "--fast", "--relaxed", "--file", name], cwd=dataset_dir)

    # --- 自动生成缺失的标准文件 ---
    if not has_readme:
        print("📝 Generating standard README.md...")
        with open(os.path.join(dataset_dir, "README.md"), "w", encoding="utf-8") as f:
            f.write(generate_readme(record, total_size, size_unit))
        run(["git", "add", "README.md"], cwd=dataset_dir)

    # --- 处理 DATS.json (补全缺失字段) ---
    dats_path = os.path.join(dataset_dir, "DATS.json")
    perfect_dats = generate_dats_json(record, total_size, size_unit, len(files))
    
    if os.path.exists(dats_path):
        print("📝 Existing DATS.json found, filling in missing mandatory fields...")
        try:
            with open(dats_path, 'r', encoding="utf-8") as f:
                final_dats = json.load(f)
            
            # 补全顶层字段
            for key in ["types", "licenses", "keywords", "version"]:
                if key not in final_dats or not final_dats[key]:
                    final_dats[key] = perfect_dats[key]
            
            # 补全 distributions.formats
            if "distributions" in final_dats and final_dats["distributions"]:
                for dist in final_dats["distributions"]:
                    if "formats" not in dist:
                        dist["formats"] = ["N/A"]
            else:
                final_dats["distributions"] = perfect_dats["distributions"]
                
            # 补全 extraProperties
            existing_props = final_dats.get("extraProperties", [])
            existing_cats = {p["category"] for p in existing_props if "category" in p}
            for p in perfect_dats["extraProperties"]:
                if p["category"] not in existing_cats:
                    existing_props.append(p)
            final_dats["extraProperties"] = existing_props
        except Exception as e:
            print(f"⚠️  Error reading existing DATS.json ({e}), using generated one.")
            final_dats = perfect_dats
    else:
        print("📝 Generating standard DATS.json...")
        final_dats = perfect_dats

    if os.path.lexists(dats_path):
        os.remove(dats_path)
        
    with open(dats_path, "w", encoding="utf-8") as f:
        json.dump(final_dats, f, indent=4, ensure_ascii=False)
    run(["git", "add", "DATS.json"], cwd=dataset_dir)

    # 生成爬虫记录文件
    with open(os.path.join(dataset_dir, ".conp-zenodo-crawler.json"), "w") as f:
        json.dump({"record_id": record_id, "import_date": dt.datetime.now().isoformat()}, f, indent=4)
    run(["git", "add", ".conp-zenodo-crawler.json"], cwd=dataset_dir)

    print("💾 Saving dataset state...")
    run(["datalad", "save", "-m", f"Import Zenodo {record_id} with standardized metadata and mixed storage"], cwd=dataset_dir)
    print(f"\n✅ Success! Dataset ready at {dataset_dir}")

if __name__ == "__main__":
    main()
