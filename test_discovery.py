#!/usr/bin/env python3
"""Test version - prints only, does not send email"""

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
    """Test version"""
    print("=" * 60)
    print("Test mode - no email will be sent")
    print("=" * 60)
    
    user_config = load_config()
    conp_dataset_path = user_config.get('conp-dataset_path', '/data/crawler/conp-dataset')
    projects_dir = os.path.join(conp_dataset_path, 'projects')
    
    # Fetch local projects
    print(f"\n1. Scanning {projects_dir}")
    if os.path.exists(projects_dir):
        projects = [d for d in os.listdir(projects_dir) if os.path.isdir(os.path.join(projects_dir, d))]
        print(f"   Local projects: {len(projects)}")
        print(f"   First 10 projects: {projects[:10]}")
    else:
        print(f"   Directory does not exist!")
        return
    
    # Test the Zenodo API
    print("\n2. Testing Zenodo API...")
    import requests
    
    # Use the token from the config file
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
        print(f"   Status code: {r.status_code}")
        
        if r.status_code == 200:
            data = r.json()
            hits = data.get('hits', {}).get('hits', [])
            print(f"   Found {len(hits)} matching datasets")
            
            for hit in hits[:5]:
                metadata = hit.get('metadata', {})
                title = metadata.get('title', 'No title')
                print(f"   - {title[:60]}...")
        else:
            print(f"   Error: {r.text[:200]}")
    except Exception as e:
        print(f"   Exception: {e}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main_test()
