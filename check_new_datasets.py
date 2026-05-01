#!/usr/bin/env python3
"""
check_new_datasets.py - 检查 OSF/Zenodo 上标记了 canadian-open-neuroscience-platform 的新数据集
通过 DATS.json 中的标识符进行对比，比文件夹名更准确
"""

import os
import re
import json
import requests
import subprocess
from email.message import EmailMessage
from datetime import datetime
from typing import List, Dict, Set, Optional, Union

def load_config():
    """加载用户配置文件"""
    config_path = os.path.expanduser("~/.conp_crawler_config.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}

def get_local_project_identifiers(projects_dir: str) -> Dict[str, Dict]:
    """
    从本地项目的 DATS.json 中提取标识符
    返回: {folder_name: {identifiers: [], title, dats_path}}
    """
    projects_data = {}
    
    if not os.path.exists(projects_dir):
        print(f"警告: projects 目录不存在: {projects_dir}")
        return projects_data
    
    for folder in os.listdir(projects_dir):
        folder_path = os.path.join(projects_dir, folder)
        if not os.path.isdir(folder_path):
            continue
        
        # 查找 DATS.json 或 dats.json (大小写不敏感)
        dats_path = None
        for filename in os.listdir(folder_path):
            if filename.lower() == 'dats.json':
                dats_path = os.path.join(folder_path, filename)
                break
        
        if not dats_path:
            # 如果没有 DATS.json，尝试找软链接
            for item in os.listdir(folder_path):
                item_path = os.path.join(folder_path, item)
                if os.path.islink(item_path) and item.lower() == 'dats.json':
                    dats_path = item_path
                    break
        
        if not dats_path:
            # 没有 DATS.json，用文件夹名作为标识符
            print(f"  警告: {folder} 没有 DATS.json，使用文件夹名作为标识符")
            projects_data[folder] = {
                'folder_name': folder,
                'title': folder,
                'identifiers': [folder],
                'source': 'unknown',
                'dats_path': None
            }
            continue
        
        try:
            # 读取 DATS.json
            with open(dats_path, 'r') as f:
                dats_content = json.load(f)
            
            # 收集所有可能的标识符（转为字符串）
            identifiers = []
            
            # DOI 字段
            doi = dats_content.get('doi')
            if doi:
                identifiers.append(str(doi))
                # 提取数字部分
                if 'zenodo' in str(doi).lower():
                    zenodo_id = str(doi).split('/')[-1]
                    identifiers.append(zenodo_id)
            
            # identifier 字段（可能是字符串或字典）
            identifier = dats_content.get('identifier')
            if identifier:
                if isinstance(identifier, dict):
                    if 'identifier' in identifier:
                        identifiers.append(str(identifier['identifier']))
                else:
                    identifiers.append(str(identifier))
            
            # extraProperties 中的标识符
            for prop in dats_content.get('extraProperties', []):
                category = prop.get('category', '')
                if category in ['identifier', 'osf_id', 'zenodo_id', 'record_id', 'concept_id']:
                    for value in prop.get('values', []):
                        val = value.get('value')
                        if val:
                            identifiers.append(str(val))
            
            # 从 URL 中提取 ID
            url = dats_content.get('url', '')
            if 'zenodo.org' in url:
                zenodo_match = re.search(r'/record/(\d+)', url)
                if zenodo_match:
                    identifiers.append(zenodo_match.group(1))
            if 'osf.io' in url:
                osf_match = re.search(r'osf\.io/([a-z0-9]+)', url)
                if osf_match:
                    identifiers.append(osf_match.group(1))
            
            # 去掉 None 和空字符串，并去重
            identifiers = list(set([i for i in identifiers if i]))
            
            projects_data[folder] = {
                'folder_name': folder,
                'title': dats_content.get('title', folder),
                'identifiers': identifiers,
                'source': dats_content.get('source', 'unknown'),
                'dats_path': dats_path
            }
            
        except Exception as e:
            print(f"  警告: 读取 {folder}/DATS.json 失败: {e}")
            projects_data[folder] = {
                'folder_name': folder,
                'title': folder,
                'identifiers': [folder],
                'source': 'unknown',
                'dats_path': None
            }
    
    return projects_data

def fetch_zenodo_datasets(user_config: Dict) -> List[Dict]:
    """从 Zenodo 获取标记了 canadian-open-neuroscience-platform 的公开数据集"""
    datasets = []
    
    headers = {}
    zenodo_tokens = user_config.get('zenodo_tokens', {})
    if zenodo_tokens:
        first_token = list(zenodo_tokens.values())[0]
        headers['Authorization'] = f'Bearer {first_token}'
    
    params = {
        'q': 'keywords:"canadian-open-neuroscience-platform"',
        'type': 'dataset',
        'access_right': 'open',
        'size': 100
    }
    
    try:
        print(f"正在从 Zenodo 获取公开数据集...")
        response = requests.get(
            'https://zenodo.org/api/records/', 
            params=params, 
            headers=headers,
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            
            for record in data.get('hits', {}).get('hits', []):
                metadata = record.get('metadata', {})
                
                title = metadata.get('title', 'Unknown Title')
                title = re.sub(r'<[^>]+>', '', title)
                
                creators = []
                for creator in metadata.get('creators', []):
                    name = creator.get('name', '')
                    if name:
                        creators.append(name)
                
                files = []
                for file_info in record.get('files', []):
                    files.append({
                        'filename': file_info.get('key', ''),
                        'size': file_info.get('size', 0),
                        'download_url': file_info.get('links', {}).get('download', '')
                    })
                
                # 收集所有标识符
                identifiers = []
                doi = metadata.get('doi')
                if doi:
                    identifiers.append(str(doi))
                
                record_id = str(record.get('id'))
                identifiers.append(record_id)
                
                concept_id = metadata.get('conceptrecid')
                if concept_id:
                    identifiers.append(str(concept_id))
                
                dataset = {
                    'source': 'zenodo',
                    'title': title,
                    'identifiers': identifiers,
                    'doi': doi,
                    'record_id': record_id,
                    'concept_id': concept_id,
                    'version': metadata.get('version', '1.0.0'),
                    'description': re.sub(r'<[^>]+>', '', metadata.get('description', ''))[:500],
                    'creators': creators,
                    'url': f"https://zenodo.org/record/{record_id}",
                    'files_count': len(files),
                    'files': files
                }
                datasets.append(dataset)
            
            print(f"从 Zenodo 获取到 {len(datasets)} 个公开数据集")
        else:
            print(f"Zenodo API 错误: {response.status_code}")
            
    except Exception as e:
        print(f"Zenodo API 错误: {e}")
    
    return datasets

def fetch_osf_datasets(user_config: Dict) -> List[Dict]:
    """从 OSF 获取标记了 canadian-open-neuroscience-platform 的公共数据集"""
    datasets = []
    
    headers = {}
    osf_token = user_config.get('osf_token')
    if osf_token:
        headers['Authorization'] = f'Bearer {osf_token}'
    
    params = {
        'filter[tags]': 'canadian-open-neuroscience-platform',
        'filter[public]': 'true',
        'page[size]': 100
    }
    
    try:
        print(f"正在从 OSF 获取公共数据集...")
        response = requests.get(
            'https://api.osf.io/v2/nodes/', 
            params=params, 
            headers=headers,
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            
            for node in data.get('data', []):
                attributes = node.get('attributes', {})
                
                node_id = node.get('id')
                
                files = []
                try:
                    files_url = f"https://api.osf.io/v2/nodes/{node_id}/files/"
                    file_response = requests.get(files_url, headers=headers, timeout=10)
                    if file_response.status_code == 200:
                        file_data = file_response.json()
                        for item in file_data.get('data', []):
                            if item.get('type') == 'files':
                                file_attr = item.get('attributes', {})
                                files.append({
                                    'filename': file_attr.get('name', ''),
                                    'size': file_attr.get('size', 0),
                                    'download_url': file_attr.get('links', {}).get('download', '')
                                })
                except Exception:
                    pass
                
                dataset = {
                    'source': 'osf',
                    'title': attributes.get('title', 'Unknown Title'),
                    'identifiers': [node_id],
                    'osf_id': node_id,
                    'description': (attributes.get('description') or '')[:500],
                    'url': f"https://osf.io/{node_id}/",
                    'files': files,
                    'files_count': len(files),
                    'tags': attributes.get('tags', [])
                }
                datasets.append(dataset)
            
            print(f"从 OSF 获取到 {len(datasets)} 个公共数据集")
        else:
            print(f"OSF API 错误: {response.status_code}")
            
    except Exception as e:
        print(f"OSF API 错误: {e}")
    
    return datasets

def compare_by_identifiers(remote_datasets: List[Dict], local_projects: Dict[str, Dict]) -> Dict:
    """
    通过标识符对比远程数据集和本地项目
    返回: {'new': [...], 'existing': [...]}
    """
    result = {
        'new': [],
        'existing': []
    }
    
    # 收集所有本地标识符（转为小写字符串）
    local_identifiers = set()
    for folder, info in local_projects.items():
        for identifier in info.get('identifiers', []):
            if identifier:
                local_identifiers.add(str(identifier).lower())
    
    print(f"   本地唯一标识符数量: {len(local_identifiers)}")
    
    for dataset in remote_datasets:
        matched = False
        matched_folder = None
        
        # 检查是否匹配任何本地标识符
        for remote_id in dataset.get('identifiers', []):
            if remote_id and str(remote_id).lower() in local_identifiers:
                matched = True
                # 找到匹配的文件夹
                for folder, info in local_projects.items():
                    for local_id in info.get('identifiers', []):
                        if local_id and str(remote_id).lower() == str(local_id).lower():
                            matched_folder = folder
                            break
                    if matched_folder:
                        break
                break
        
        # 如果没有匹配到标识符，尝试用标题匹配文件夹名
        if not matched:
            folder_name = re.sub(r'\W|^(?=\d)', '_', dataset['title'])
            if folder_name in local_projects:
                matched = True
                matched_folder = folder_name
        
        if matched:
            result['existing'].append({
                **dataset,
                'folder_name': matched_folder
            })
        else:
            folder_name = re.sub(r'\W|^(?=\d)', '_', dataset['title'])
            result['new'].append({
                **dataset,
                'folder_name': folder_name
            })
    
    return result

def format_size(size_bytes):
    """格式化文件大小"""
    if size_bytes == 0:
        return "0 B"
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.1f} {size_names[i]}"

def send_email_notification(new_datasets: List[Dict], existing_count: int, user_config: Dict):
    """发送邮件通知"""
    
    if not new_datasets:
        print("没有新数据集需要通知")
        return
    
    recipient = user_config.get('notify_email', 'wangshen.mcin@gmail.com')
    
    msg = EmailMessage()
    msg["To"] = recipient
    msg["From"] = "conp-bot@localhost"
    msg["Subject"] = f"[CONP crawler] New Public Datasets - {datetime.now().strftime('%Y-%m-%d')}"
    
    content_lines = [
        "=" * 80,
        "CONP DATASET DISCOVERY REPORT (by identifier matching)",
        "=" * 80,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"📊 SUMMARY:",
        f"   - Local projects: {existing_count}",
        f"   - New public datasets: {len(new_datasets)}",
        "",
        "=" * 80,
        "NEW PUBLIC DATASETS",
        "=" * 80,
        "",
    ]
    
    for idx, ds in enumerate(new_datasets, 1):
        content_lines.extend([
            f"[{idx}] {ds['title']}",
            "-" * 60,
            f"   Source:     {ds['source'].upper()}",
            f"   URL:        {ds.get('url', 'N/A')}",
            f"   Identifiers: {', '.join(ds.get('identifiers', [])[:5])}",
            f"   Folder:     {ds['folder_name']}",
            "",
        ])
        
        if ds.get('description'):
            desc = ds['description'].replace('\n', ' ').strip()
            if len(desc) > 200:
                desc = desc[:200] + "..."
            content_lines.append(f"   Description: {desc}")
        
        if ds.get('files'):
            content_lines.append(f"   Files: {len(ds['files'])}")
            for file in ds['files'][:10]:
                size_str = format_size(file.get('size', 0))
                content_lines.append(f"      - {file.get('filename', 'unknown')} ({size_str})")
            if len(ds['files']) > 10:
                content_lines.append(f"      ... and {len(ds['files']) - 10} more files")
        
        content_lines.extend([
            "",
            "-" * 60,
            ""
        ])
    
    content_lines.extend([
        "=" * 80,
        f"End of Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 80
    ])
    
    msg.set_content("\n".join(content_lines))
    
    try:
        subprocess.run(
            ["/usr/sbin/sendmail", "-t"],
            input=msg.as_bytes(),
            check=True,
        )
        print(f"✓ 邮件已发送到: {recipient}")
    except Exception as e:
        print(f"✗ 邮件发送失败: {e}")

def save_report(new_datasets: List[Dict], log_dir: str):
    """保存报告"""
    os.makedirs(log_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    report = {
        'timestamp': datetime.now().isoformat(),
        'summary': {
            'new_public': len(new_datasets)
        },
        'new_datasets': new_datasets
    }
    
    report_file = os.path.join(log_dir, f"dataset_discovery_{timestamp}.json")
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"✓ 报告已保存: {report_file}")

def main():
    """主函数"""
    print("=" * 60)
    print("CONP Dataset Discovery Tool")
    print("Matching by identifiers from DATS.json")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    user_config = load_config()
    conp_dataset_path = user_config.get('conp-dataset_path', '/data/crawler/conp-dataset')
    projects_dir = os.path.join(conp_dataset_path, 'projects')
    log_dir = os.path.join(conp_dataset_path, 'log')
    
    print(f"\nProjects 目录: {projects_dir}")
    
    print("\n1. 读取本地项目的 DATS.json...")
    local_projects = get_local_project_identifiers(projects_dir)
    print(f"   找到 {len(local_projects)} 个本地项目")
    
    # 显示部分标识符示例
    count = 0
    for folder, info in local_projects.items():
        if info.get('identifiers') and count < 5:
            print(f"   {folder}: {info['identifiers'][:3]}")
            count += 1
    
    print("\n2. 从 Zenodo 获取公开数据集...")
    zenodo_datasets = fetch_zenodo_datasets(user_config)
    
    print("\n3. 从 OSF 获取公共数据集...")
    osf_datasets = fetch_osf_datasets(user_config)
    
    all_remote = zenodo_datasets + osf_datasets
    print(f"\n   总共获取到 {len(all_remote)} 个公开远程数据集")
    
    print("\n4. 通过标识符对比本地和远程...")
    comparison = compare_by_identifiers(all_remote, local_projects)
    
    print(f"\n   已存在数据集: {len(comparison['existing'])}")
    print(f"   ✨ 新数据集: {len(comparison['new'])}")
    
    if comparison['new']:
        print(f"\n📦 新发现 {len(comparison['new'])} 个公开数据集:")
        print("=" * 80)
        for i, ds in enumerate(comparison['new'], 1):
            print(f"\n{i:2}. {ds['title']}")
            print(f"     Source: {ds['source'].upper()}")
            print(f"     URL: {ds.get('url', 'N/A')}")
            print(f"     Identifiers: {', '.join(ds.get('identifiers', [])[:3])}")
            print(f"     Folder: {ds['folder_name']}")
            if ds.get('files'):
                print(f"     Files: {len(ds['files'])}")
            print("-" * 60)
    else:
        print("\n没有发现新的公开数据集")
    
    print("\n5. 发送邮件通知...")
    send_email_notification(comparison['new'], len(local_projects), user_config)
    
    print("\n6. 保存报告...")
    save_report(comparison['new'], log_dir)
    
    print("\n" + "=" * 60)
    print("完成!")
    print("=" * 60)

if __name__ == "__main__":
    main()
