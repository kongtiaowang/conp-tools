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
    # 移除或替换特殊字符
    clean = re.sub(r'[<>:"/\\|?*]', '_', title)
    clean = re.sub(r'\s+', '_', clean)
    clean = re.sub(r'_+', '_', clean)
    clean = clean.strip('_')
    # 如果以数字开头，添加前缀
    if clean and clean[0].isdigit():
        clean = f"dataset_{clean}"
    return clean

def html_to_text(value: str) -> str:
    """将 HTML 转换为纯文本"""
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    # 清理多余的空白
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

        # 注册 URL 元数据，不下载内容
        run(["git", "annex", "addurl", url, "--fast", "--file", name], cwd=dataset_dir)
        
        if file_item.get("size"):
            file_sizes.append(int(file_item["size"]))

def generate_readme(record: dict, dataset_dir: str, file_sizes: list[int]) -> str:
    """生成 README.md 文件"""
    metadata = record.get("metadata", {})
    record_id = record.get("id")
    
    # 计算总大小
    total_size_bytes = sum(file_sizes)
    size_val, size_unit = natural_size(total_size_bytes)
    
    # 生成 README 内容
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
    
    # 添加创作者信息
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

def generate_dats_json(record: dict, total_size: float, size_unit: str) -> dict:
    """生成 DATS.json 文件"""
    metadata = record.get("metadata", {})
    record_id = record.get("id")
    homepage = record.get("links", {}).get("self_html", f"https://zenodo.org/records/{record_id}")
    
    # 收集标识符
    identifiers = []
    doi = metadata.get("doi")
    if doi:
        identifiers.append({"identifier": doi, "identifierSource": "DOI"})
    
    # 收集 extra properties
    extra_properties = [
        {"category": "zenodo_record_id", "values": [{"value": str(record_id)}]},
        {"category": "logo", "values": [{"value": "https://about.zenodo.org/static/img/logos/zenodo-gradient-round.svg"}]},
        {"category": "source", "values": [{"value": "zenodo"}]}
    ]
    
    # 添加概念 DOI
    concept_id = record.get("conceptrecid")
    if concept_id:
        extra_properties.append({"category": "concept_id", "values": [{"value": str(concept_id)}]})
    
    # 添加版本信息
    if metadata.get("version"):
        extra_properties.append({"category": "version", "values": [{"value": metadata["version"]}]})
    
    # 添加关键词
    keywords = []
    for kw in metadata.get("keywords", []):
        keywords.append({"value": kw})
    
    dats = {
        "name": metadata.get("title", "Untitled Dataset"),
        "title": metadata.get("title", "Untitled Dataset"),
        "identifier": identifiers[0] if identifiers else {"identifier": str(record_id), "identifierSource": "ZENODO"},
        "version": metadata.get("version", "1.0.0"),
        "storedIn": {
            "name": "Zenodo",
            "url": "https://zenodo.org",
            "identifier": {"identifier": "https://zenodo.org", "identifierSource": "URL"}
        },
        "creators": [{"name": c.get("name")} for c in metadata.get("creators", [])],
        "description": html_to_text(metadata.get("description", "")),
        "license": metadata.get("license", {}).get("id", "Unknown"),
        "distribution": [{
            "access": {
                "landingPage": homepage,
                "authorizations": [{"value": "public"}]
            },
            "size": total_size,
            "unit": {"value": size_unit}
        }],
        "dates": [{
            "date": metadata.get("publication_date", dt.datetime.now().strftime("%Y-%m-%d")),
            "type": {"value": "PublicationDate"}
        }],
        "types": ["dataset"],
        "keywords": keywords,
        "extraProperties": extra_properties,
        "source": "zenodo",
        "url": homepage
    }
    
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
    
    # 生成 DATS.json
    print("Generating DATS.json...")
    dats_content = generate_dats_json(record, total_size, size_unit)
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
