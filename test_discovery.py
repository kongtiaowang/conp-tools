#!/usr/bin/env python3
"""测试版本 - 只打印不发送邮件"""

import sys
import os
import json

sys.path.insert(0, '/data/crawler/conp-dataset')

def load_config():
    config_path = os.path.expanduser("~/.conp_crawler_config.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}

def main_test():
    """测试版本"""
    print("=" * 60)
    print("测试模式 - 不会发送邮件")
    print("=" * 60)
    
    user_config = load_config()
    conp_dataset_path = user_config.get('conp-dataset_path', '/data/crawler/conp-dataset')
    projects_dir = os.path.join(conp_dataset_path, 'projects')
    
    # 获取本地项目
    print(f"\n1. 扫描 {projects_dir}")
    if os.path.exists(projects_dir):
        projects = [d for d in os.listdir(projects_dir) if os.path.isdir(os.path.join(projects_dir, d))]
        print(f"   本地项目数: {len(projects)}")
        print(f"   前10个项目: {projects[:10]}")
    else:
        print(f"   目录不存在!")
        return
    
    # 测试 Zenodo API
    print("\n2. 测试 Zenodo API...")
    import requests
    
    # 使用配置文件中的 token
    headers = {}
    zenodo_tokens = user_config.get('zenodo_tokens', {})
    if zenodo_tokens:
        first_token = list(zenodo_tokens.values())[0]
        headers['Authorization'] = f'Bearer {first_token}'
    
    params = {
        'q': 'canadian-open-neuroscience-platform',
        'type': 'dataset',
        'size': 10
    }
    
    try:
        r = requests.get('https://zenodo.org/api/records/', params=params, headers=headers, timeout=30)
        print(f"   状态码: {r.status_code}")
        
        if r.status_code == 200:
            data = r.json()
            hits = data.get('hits', {}).get('hits', [])
            print(f"   找到 {len(hits)} 个相关数据集")
            
            for hit in hits[:5]:
                metadata = hit.get('metadata', {})
                title = metadata.get('title', 'No title')
                print(f"   - {title[:60]}...")
        else:
            print(f"   错误: {r.text[:200]}")
    except Exception as e:
        print(f"   异常: {e}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main_test()
