#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Dict, Any

# 定义需要直接保存为普通文件的后缀
TEXT_EXTENSIONS = {'.csv', '.json', '.md', '.txt', '.py', '.yml', '.yaml', '.tsv', '.jsonld', '.html'}
TEXT_FILENAMES = {'README', 'LICENSE', 'CHANGES', 'AUTHORS', 'MANIFEST', 'DESCRIPTION'}

def is_text_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    base = os.path.basename(filename).upper()
    return ext in TEXT_EXTENSIONS or base in TEXT_FILENAMES

OSF_PROVIDER_CONFIG = """[provider:OSF]
url_re = .*osf\\.io.*
authentication_type = bearer_token
credential = OSF

[credential:OSF]
# If known, specify URL or email to how/where to request credentials
# url = ???
type = token
"""

def run(cmd: list[str], cwd: str | None = None):
    subprocess.run(cmd, cwd=cwd, check=True)

def capture(cmd: list[str], cwd: str | None = None) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True)

def clean_title(title: str) -> str:
    """标题安全化，限制在 80 字符"""
    clean = re.sub(r'[<>:"/\\|?*]', '_', title)
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
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    return (round(size, 2), unit)

def normalize_node(node: str) -> str:
    node = node.strip().rstrip("/")
    if "/nodes/" in node:
        return node.split("/nodes/")[-1].split("/")[0]
    if "osf.io/" in node:
        return node.split("osf.io/")[-1].split("/")[0]
    return node

def load_osf_token(config_path: str | None, arg_token: str | None) -> str | None:
    if arg_token:
        return arg_token
    env_token = os.getenv("OSF_TOKEN") or os.getenv("DATALAD_OSF_token")
    if env_token:
        return env_token
    if config_path and os.path.isfile(config_path):
        try:
            with open(config_path) as f:
                data = json.load(f)
            return data.get("osf_token")
        except: pass
    return None

def request(url: str, token: str | None = None, redirect: bool = True):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    if redirect:
        return urllib.request.urlopen(req, timeout=120)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    return opener.open(req, timeout=120)

def fetch_json(url: str, token: str | None = None) -> dict:
    with request(url, token=token) as response:
        return json.loads(response.read().decode("utf-8"))

def fetch_paginated_data(url: str, token: str | None = None) -> list[dict]:
    items = []
    while url:
        payload = fetch_json(url, token=token)
        items.extend(payload.get("data", []))
        url = payload.get("links", {}).get("next")
    return items

def configure_git_attributes(dataset_dir: str):
    """配置 .gitattributes 确保文本文件不进 Annex"""
    attr_path = os.path.join(dataset_dir, ".gitattributes")
    patterns = [
        "README.md annex.largefiles=nothing",
        "DATS.json annex.largefiles=nothing",
        ".conp-osf-crawler.json annex.largefiles=nothing",
        "*.csv annex.largefiles=nothing",
        "*.json annex.largefiles=nothing",
        "*.txt annex.largefiles=nothing",
        ".gitattributes annex.largefiles=nothing"
    ]
    with open(attr_path, "w") as f:
        f.write("\n".join(patterns) + "\n")
    run(["git", "add", ".gitattributes"], cwd=dataset_dir)

def ensure_osf_provider(dataset_dir: str, token: str | None):
    if not token: return
    datalad_dir = os.path.join(dataset_dir, ".datalad")
    providers_dir = os.path.join(datalad_dir, "providers")
    os.makedirs(providers_dir, exist_ok=True)
    config_path = os.path.join(providers_dir, "OSF.cfg")
    with open(config_path, "w") as f:
        f.write(OSF_PROVIDER_CONFIG)
    run(["git", "add", ".datalad/providers/OSF.cfg"], cwd=dataset_dir)
    os.environ["DATALAD_OSF_token"] = token

def download_file_directly(url: str, dest_path: str, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as response, open(dest_path, "wb") as out_file:
        out_file.write(response.read())

def download_files(files_link: str, current_dir: str, inner_path: str, dataset_dir: str, token: str | None, file_sizes: list[int]):
    for file_item in fetch_paginated_data(files_link, token):
        attributes = file_item.get("attributes", {})
        kind = attributes.get("kind")
        name = attributes.get("name")
        if not name: continue

        if kind == "folder":
            folder_current_dir = os.path.join(current_dir, name)
            folder_inner_path = os.path.join(inner_path, name)
            os.makedirs(folder_current_dir, exist_ok=True)
            download_files(file_item["relationships"]["files"]["links"]["related"]["href"],
                           folder_current_dir, folder_inner_path, dataset_dir, token, file_sizes)
            continue

        if kind != "file": continue

        target_rel = os.path.join(inner_path, name) if inner_path else name
        target_abs = os.path.join(dataset_dir, target_rel)
        
        # 确保父目录存在
        parent_dir = os.path.dirname(target_abs)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        
        download_url = file_item["links"]["download"]
        
        if is_text_file(name):
            print(f"   📄 [TEXT] Downloading: {target_rel}")
            try:
                # 🌟 修复：如果文件已存在（可能是 Annex 链接），先删除它，否则 open() 会报错
                if os.path.lexists(target_abs):
                    os.remove(target_abs)
                
                download_file_directly(download_url, target_abs, token)
                run(["git", "add", target_rel], cwd=dataset_dir)
            except Exception as e:
                print(f"   ⚠️  Download failed for {target_rel}: {e}. Falling back to Annex.")
                run(["git", "annex", "addurl", download_url, "--fast", "--relaxed", "--file", target_rel], cwd=dataset_dir)
        else:
            print(f"   📦 [LARGE] Adding URL: {target_rel}")
            run(["git", "annex", "addurl", download_url, "--fast", "--relaxed", "--file", target_rel], cwd=dataset_dir)
            
        file_size = attributes.get("size")
        if file_size: file_sizes.append(int(file_size))

def download_components(components: list[dict], dataset_dir: str, token: str | None, file_sizes: list[int], inner_path: str = ""):
    for component in components:
        component_title = clean_title(component.get("attributes", {}).get("title", "component"))
        component_inner_path = os.path.join(inner_path, "components", component_title)
        os.makedirs(os.path.join(dataset_dir, component_inner_path), exist_ok=True)
        download_files(component["relationships"]["files"]["links"]["related"]["href"],
                       os.path.join(dataset_dir, component_inner_path), component_inner_path, dataset_dir, token, file_sizes)
        subcomponents = fetch_paginated_data(component["relationships"]["children"]["links"]["related"]["href"], token)
        if subcomponents:
            download_components(subcomponents, dataset_dir, token, file_sizes, component_inner_path)

def generate_readme(dataset: dict, total_size: float, size_unit: str) -> str:
    content = f'# {dataset["title"]}\n\nCrawled from [OSF]({dataset["homepage"]})'
    if dataset.get("description"):
        content += f'\n\n## Description\n\n{html_to_text(dataset["description"])}'
    if dataset.get("identifier"):
        content += f'\n\n## Identifier (DOI)\n\n{dataset["identifier"]["identifier"]}'
    content += f'\n\n## Metadata\n- **Total Size**: {total_size} {size_unit}\n- **Version**: {dataset["version"]}'
    if dataset.get("wiki"):
        content += f'\n\n## Wiki Summary\n\n{html_to_text(dataset["wiki"])[:1000]}...'
    content += "\n\n---\n*Automatically imported via CONP-OSF-Crawler*"
    return content

def generate_dats_json(dataset: dict, total_size: float, size_unit: str, file_count: int) -> dict:
    return {
        "title": dataset["title"],
        "description": html_to_text(dataset.get("description", "")),
        "creators": dataset.get("creators", []),
        "version": dataset.get("version", "1.0.0"),
        "types": [{"information": {"value": "dataset"}}],
        "licenses": dataset.get("licenses", [{"name": "None"}]),
        "keywords": dataset.get("keywords", [{"value": "N/A"}]),
        "distributions": [{
            "size": total_size,
            "unit": {"value": size_unit},
            "access": {"landingPage": dataset["homepage"]},
            "formats": ["N/A"]
        }],
        "extraProperties": dataset.get("extraProperties", []) + [
            {"category": "source", "values": [{"value": "osf"}]},
            {"category": "osf_node_id", "values": [{"value": dataset["node_id"]}]},
            {"category": "files", "values": [{"value": str(file_count)}]},
            {"category": "subjects", "values": [{"value": "N/A"}]},
            {"category": "CONP_status", "values": [{"value": "CONP"}]}
        ]
    }

def main():
    parser = argparse.ArgumentParser(description="Import OSF dataset with DataLad and standardized metadata.")
    parser.add_argument("--node", required=True, help="OSF node id or URL")
    parser.add_argument("--basedir", default=".")
    parser.add_argument("--osf-token")
    args = parser.parse_args()

    node_id = normalize_node(args.node)
    token = load_osf_token(None, args.osf_token)

    print(f"📥 Fetching OSF node {node_id}...")
    node_data = fetch_json(f"https://api.osf.io/v2/nodes/{node_id}/", token)["data"]
    
    # 模拟 build_description 逻辑
    relationships = node_data["relationships"]
    attributes = node_data["attributes"]
    
    dataset = {
        "node_id": node_id,
        "title": attributes["title"],
        "homepage": node_data["links"]["html"],
        "description": attributes.get("description", ""),
        "version": attributes["date_modified"],
        "files_link": relationships["files"]["links"]["related"]["href"],
        "creators": [{"name": c} for c in ["Multiple Contributors"]], # 简化处理，可后续丰富
    }
    
    # 获取 Wiki (可选)
    try:
        wikis = fetch_paginated_data(relationships["wikis"]["links"]["related"]["href"], token)
        if wikis:
            with request(wikis[0]["links"]["download"], token=token) as response:
                dataset["wiki"] = response.read().decode("utf-8")
    except: pass

    folder_name = clean_title(dataset["title"])
    dataset_dir = os.path.abspath(os.path.join(args.basedir, "projects", folder_name))
    os.makedirs(dataset_dir, exist_ok=True)

    print("🚀 Initializing DataLad...")
    run(["datalad", "create", "--force", "."], cwd=dataset_dir)
    configure_git_attributes(dataset_dir)
    ensure_osf_provider(dataset_dir, token)

    file_sizes = []
    print("🔗 Downloading files...")
    download_files(dataset["files_link"], dataset_dir, "", dataset_dir, token, file_sizes)
    
    # 获取组件
    components = fetch_paginated_data(relationships["children"]["links"]["related"]["href"], token)
    if components:
        print(f"📦 Downloading {len(components)} components...")
        download_components(components, dataset_dir, token, file_sizes)

    total_size, size_unit = natural_size(sum(file_sizes))

    print("📝 Generating metadata...")
    with open(os.path.join(dataset_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(generate_readme(dataset, total_size, size_unit))
    
    with open(os.path.join(dataset_dir, "DATS.json"), "w", encoding="utf-8") as f:
        json.dump(generate_dats_json(dataset, total_size, size_unit, len(file_sizes)), f, indent=4, ensure_ascii=False)

    with open(os.path.join(dataset_dir, ".conp-osf-crawler.json"), "w") as f:
        json.dump({"node_id": node_id, "version": dataset["version"]}, f, indent=4)

    run(["git", "add", "README.md", "DATS.json", ".conp-osf-crawler.json"], cwd=dataset_dir)
    print("💾 Saving dataset state...")
    run(["datalad", "save", "-m", f"Import OSF node {node_id} with mixed storage"], cwd=dataset_dir)
    
    print(f"\n✅ Success! OSF Dataset ready at {dataset_dir}")

if __name__ == "__main__":
    main()
