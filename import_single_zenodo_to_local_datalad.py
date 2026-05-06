#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import urllib.request
from typing import List, Dict, Any

ZENODO_PROVIDER_CONFIG = """[provider:ZENODO]
url_re = .*zenodo\\.org.*
authentication_type = bearer_token
credential = ZENODO

[credential:ZENODO]
type = token
"""

def run(cmd: list[str], cwd: str | None = None):
    subprocess.run(cmd, cwd=cwd, check=True)

def capture(cmd: list[str], cwd: str | None = None) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True)

def clean_title(title: str) -> str:
    """将标题转换为安全的文件夹名"""
    clean = re.sub(r'[<>:"/\\|?*]', '_', title)
    clean = re.sub(r'\s+', '_', clean)
    clean = re.sub(r'_+', '_', clean)
    clean = clean.strip('_')
    if clean and clean[0].isdigit():
        clean = f"dataset_{clean}"
    return clean

def html_to_text(value: str) -> str:
    """将 HTML 转换为纯文本"""
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()

def natural_size(num_bytes: int) -> tuple[float, str]:
    """格式化文件大小"""
    units = ["Bytes", "KB", "MB", "GB", "TB", "PB"]
    size = float(num_bytes)
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    return (round(size, 2), unit)

def load_zenodo_token(config_path: str | None, arg_token: str | None) -> str | None:
    """加载 Zenodo token"""
    if arg_token:
        return arg_token
    env_token = os.getenv("ZENODO_TOKEN") or os.getenv("DATALAD_ZENODO_token")
    if env_token:
        return env_token
    if config_path and os.path.isfile(config_path):
        with open(config_path) as f:
            data = json.load(f)
        return data.get("zenodo_token")
    return None

def fetch_json(url: str, token: str | None = None) -> dict:
    """获取 JSON 数据"""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))

def ensure_dataset_dir(dataset_dir: str):
    """确保数据集目录存在"""
    os.makedirs(dataset_dir, exist_ok=True)
    if not os.path.isdir(os.path.join(dataset_dir, ".datalad")):
        parent_dir = os.path.dirname(dataset_dir)
        run(["datalad", "create", "-f", os.path.basename(dataset_dir)], cwd=parent_dir)

def ensure_zenodo_provider(dataset_dir: str, token: str | None):
    """配置 Zenodo provider"""
    if not token:
        return
    providers_dir = os.path.join(dataset_dir, ".datalad", "providers")
    os.makedirs(providers_dir, exist_ok=True)
    config_path = os.path.join(providers_dir, "ZENODO.cfg")
    with open(config_path, "w") as f:
        f.write(ZENODO_PROVIDER_CONFIG)
    run(["datalad", "no-annex", "--pattern", "**/ZENODO.cfg"], cwd=dataset_dir)
    os.environ["DATALAD_ZENODO_token"] = token

def register_urls(files: list[dict], dataset_dir: str, file_sizes: list[int]):
    """在 annex 中注册 Zenodo URLs，不下载内容"""
    for file_item in files:
        name = file_item.get("key")
        url = file_item["links"]["self"]
        if not name:
            continue

        target_abs = os.path.join(dataset_dir, name)
        os.makedirs(os.path.dirname(target_abs), exist_ok=True)
        
        if os.path.lexists(target_abs):
            continue

        run(["git", "annex", "addurl", url, "--fast", "--file", name], cwd=dataset_dir)
        
        if file_item.get("size"):
            file_sizes.append(int(file_item["size"]))

def detect_dataset_type(metadata: dict) -> str:
    """检测数据集类型"""
    title = metadata.get("title", "").lower()
    description = metadata.get("description", "").lower()
    
    if "mri" in title or "mri" in description:
        return "MRI"
    elif "eeg" in title or "eeg" in description:
        return "EEG"
    elif "fmri" in title or "fmri" in description:
        return "fMRI"
    elif "histology" in title or "histology" in description:
        return "histology"
    else:
        return "dataset"

def generate_readme(record: dict, dataset_dir: str, file_sizes: list[int]) -> str:
    """生成 README.md 文件"""
    metadata = record.get("metadata", {})
    record_id = record.get("id")
    
    total_size_bytes = sum(file_sizes)
    size_val, size_unit = natural_size(total_size_bytes)
    
    readme_lines = [
        f"# {metadata.get('title', 'Untitled Dataset')}",
        "",
        "## Description",
        "",
        html_to_text(metadata.get('description', 'No description provided.')),
        "",
        "## Metadata",
        "",
        f"- **Zenodo Record ID**: {record_id}",
        f"- **DOI**: {metadata.get('doi', 'N/A')}",
        f"- **Version**: {metadata.get('version', 'N/A')}",
        f"- **Publication Date**: {metadata.get('publication_date', 'N/A')}",
        f"- **Total Size**: {size_val} {size_unit}",
        f"- **Files Count**: {len(record.get('files', []))}",
        "",
        "## Creators",
        "",
    ]
    
    for creator in metadata.get('creators', []):
        name = creator.get('name', '')
        affiliation = creator.get('affiliation', '')
        if affiliation:
            readme_lines.append(f"- {name} ({affiliation})")
        else:
            readme_lines.append(f"- {name}")
    
    readme_lines.extend([
        "",
        "## License",
        "",
        f"License: {metadata.get('license', {}).get('id', 'Not specified')}",
        "",
        "## Access",
        "",
        f"This dataset is publicly available at: https://zenodo.org/record/{record_id}",
        "",
        "## Usage",
        "",
        "To download the actual data files, run:",
        "```bash",
        "datalad get .",
        "```",
        "",
        "## Citation",
        "",
        "Please cite this dataset as:",
        "```bibtex",
        f"@dataset{{{metadata.get('doi', record_id)},",
        f"  title = {{{metadata.get('title', 'Untitled')}}},",
        f"  author = {{{' and '.join([c.get('name', '') for c in metadata.get('creators', [])])}}},",
        f"  year = {{{metadata.get('publication_date', 'N/A')[:4]}}},",
        f"  publisher = {{Zenodo}},",
        f"  version = {{{metadata.get('version', '1.0')}}},",
        f"  doi = {{{metadata.get('doi', 'N/A')}}}",
        "}",
        "```",
        "",
        "---",
        f"*Automatically imported from Zenodo on {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        "*Managed with DataLad*"
    ])
    
    return "\n".join(readme_lines)

def generate_dats_json(record: dict, total_size: float, size_unit: str, files: list) -> dict:
    """生成符合 CONP 测试要求的 DATS.json 文件"""
    metadata = record.get("metadata", {})
    record_id = record.get("id")
    homepage = record.get("links", {}).get("self_html", f"https://zenodo.org/records/{record_id}")
    
    # 获取 DOI
    doi = metadata.get("doi", "")
    if doi and not doi.startswith("http"):
        doi_url = f"https://doi.org/{doi}"
    else:
        doi_url = doi
    
    # 提取文件格式
    formats = set()
    for file_item in record.get("files", []):
        key = file_item.get("key", "")
        if "." in key:
            ext = key.split(".")[-1].upper()
            formats.add(ext)
        elif key:
            formats.add(key.split(".")[0].upper())
    
    # 获取文件数量
    num_files = len(record.get("files", []))
    
    # 收集关键词
    keywords = []
    for kw in metadata.get("keywords", []):
        keywords.append({"value": kw})
    
    # 添加默认的 CONP 关键词
    if not any(k.get("value") == "canadian-open-neuroscience-platform" for k in keywords):
        keywords.append({"value": "canadian-open-neuroscience-platform"})
    
    dats = {
        "title": metadata.get("title", "Untitled Dataset"),
        "description": html_to_text(metadata.get("description", "")),
        "identifier": {
            "identifier": doi_url,
            "identifierSource": "DOI"
        },
        "creators": [{"name": c.get("name", "")} for c in metadata.get("creators", [])],
        "version": metadata.get("version", "1.0.0"),
        "licenses": [
            {
                "name": metadata.get("license", {}).get("id", "CC-BY-4.0").upper()
            }
        ],
        "keywords": keywords,
        "distributions": [
            {
                "access": {
                    "landingPage": homepage
                },
                "size": total_size,
                "unit": {"value": size_unit},
                "formats": sorted(list(formats)) if formats else ["UNKNOWN"]
            }
        ],
        "extraProperties": [
            {"category": "zenodo_record_id", "values": [{"value": str(record_id)}]},
            {"category": "logo", "values": [{"value": "https://about.zenodo.org/static/img/logos/zenodo-gradient-round.svg"}]},
            {"category": "source", "values": [{"value": "zenodo"}]},
            {"category": "CONP_status", "values": [{"value": "external"}]},
            {"category": "subjects", "values": [{"value": "unknown"}]},
            {"category": "files", "values": [{"value": str(num_files)}]}
        ],
        "types": [
            {"information": {"value": detect_dataset_type(metadata)}}
        ]
    }
    
    # 添加概念 ID（如果有）
    concept_id = record.get("conceptrecid")
    if concept_id:
        dats["extraProperties"].append({
            "category": "concept_id",
            "values": [{"value": str(concept_id)}]
        })
    
    return dats

def create_conp_tracking_file(dataset_dir: str, record: dict, dataset_info: dict):
    """创建 CONP 追踪文件"""
    tracking = {
        "zenodo": {
            "concept_doi": dataset_info["concept_doi"],
            "version": dataset_info["version"],
            "record_id": record.get("id"),
            "import_date": dt.datetime.now().isoformat()
        },
        "title": dataset_info["title"]
    }
    
    with open(os.path.join(dataset_dir, ".conp-zenodo-crawler.json"), "w") as f:
        json.dump(tracking, f, indent=4)
    
    run(["git", "add", ".conp-zenodo-crawler.json"], cwd=dataset_dir)

def main():
    parser = argparse.ArgumentParser(description="Import Zenodo metadata/URLs into DataLad without downloading.")
    parser.add_argument("--record", required=True, help="Zenodo record id or URL")
    parser.add_argument("--basedir", default=".", help="Base directory")
    parser.add_argument("--config", default=os.path.expanduser("~/.conp_crawler_config.json"))
    parser.add_argument("--zenodo-token", help="Zenodo token")
    args = parser.parse_args()

    # 提取 record ID
    record_id = args.record
    if "zenodo.org/records/" in record_id:
        record_id = record_id.split("zenodo.org/records/")[-1].split("/")[0]

    # 获取数据
    token = load_zenodo_token(args.config, args.zenodo_token)
    print(f"Fetching Zenodo record {record_id}...")
    record = fetch_json(f"https://zenodo.org/api/records/{record_id}", token)
    
    # 构建基本信息
    dataset_info = {
        "record_id": record.get("id"),
        "concept_doi": record.get("conceptrecid"),
        "title": record.get("metadata", {}).get("title", f"Record_{record_id}"),
        "version": record.get("metadata", {}).get("version", "1.0.0")
    }
    
    # 创建数据集目录
    dataset_dir = os.path.abspath(os.path.join(args.basedir, "projects", clean_title(dataset_info["title"])))
    print(f"Creating dataset in: {dataset_dir}")
    
    ensure_dataset_dir(dataset_dir)
    ensure_zenodo_provider(dataset_dir, token)
    
    # 注册文件
    file_sizes = []
    files = record.get("files", [])
    if files:
        print(f"Registering {len(files)} files...")
        register_urls(files, dataset_dir, file_sizes)
    else:
        print("No files found in this record.")
    
    # 计算总大小
    total_size_bytes = sum(file_sizes)
    total_size, size_unit = natural_size(total_size_bytes)
    
    # 生成 README.md
    print("Generating README.md...")
    readme_content = generate_readme(record, dataset_dir, file_sizes)
    readme_path = os.path.join(dataset_dir, "README.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_content)
    run(["git", "add", "README.md"], cwd=dataset_dir)
    
    # 生成 DATS.json（传入 files 参数）
    print("Generating DATS.json...")
    dats_content = generate_dats_json(record, total_size, size_unit, files)
    dats_path = os.path.join(dataset_dir, "DATS.json")
    with open(dats_path, "w", encoding="utf-8") as f:
        json.dump(dats_content, f, indent=4, ensure_ascii=False)
    run(["git", "add", "DATS.json"], cwd=dataset_dir)
    
    # 创建追踪文件
    create_conp_tracking_file(dataset_dir, record, dataset_info)
    
    # 保存 DataLad
    commit_msg = f"Import Zenodo record {record_id}: {dataset_info['title']}"
    run(["datalad", "save", "-m", commit_msg], cwd=dataset_dir)
    
    # 输出结果
    print(f"\n✅ Success! Dataset imported to: {dataset_dir}")
    print(f"   - Files registered (not downloaded): {len(files)}")
    print(f"   - Total size: {total_size} {size_unit}")
    print(f"   - Generated: README.md, DATS.json, .conp-zenodo-crawler.json")
    print("\n📋 To download the actual data files, run:")
    print(f"   cd {dataset_dir}")
    print("   datalad get .")
    
    # 验证文件存在性
    print("\n🔍 Verifying generated files:")
    required_files = ["README.md", "DATS.json", ".conp-zenodo-crawler.json"]
    for file in required_files:
        file_path = os.path.join(dataset_dir, file)
        if os.path.exists(file_path):
            print(f"   ✓ {file}")
        else:
            print(f"   ✗ {file} (MISSING)")

if __name__ == "__main__":
    main()
