#!/usr/bin/env python3
"""
check_updates.py - Check for updates to Zenodo/OSF datasets
Uses the same query format as ZenodoCrawler
"""

import os
import json
import requests
from datetime import datetime

import sys
sys.path.insert(0, '/data/crawler/conp-dataset')


def load_config():
    config_path = os.path.expanduser("~/.conp_crawler_config.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}


def get_local_projects_info(projects_dir: str) -> dict:
    """Get local project information from trackers"""
    projects = {}

    if not os.path.exists(projects_dir):
        print(f"Warning: projects directory does not exist: {projects_dir}")
        return projects

    for folder in os.listdir(projects_dir):
        folder_path = os.path.join(projects_dir, folder)
        if not os.path.isdir(folder_path):
            continue

        # Check Zenodo tracker
        zenodo_tracker = os.path.join(folder_path, ".conp-zenodo-crawler.json")
        if os.path.exists(zenodo_tracker):
            try:
                with open(zenodo_tracker, 'r') as f:
                    tracker = json.load(f)
                    projects[folder] = {
                        'type': 'zenodo',
                        'folder': folder,
                        'title': tracker.get('title', folder),
                        'concept_doi': tracker.get('zenodo', {}).get('concept_doi'),
                        'version': tracker.get('zenodo', {}).get('version', 'unknown')
                    }
            except:
                pass

        # Check OSF tracker
        osf_tracker = os.path.join(folder_path, ".conp-osf-crawler.json")
        if os.path.exists(osf_tracker):
            try:
                with open(osf_tracker, 'r') as f:
                    tracker = json.load(f)
                    projects[folder] = {
                        'type': 'osf',
                        'folder': folder,
                        'title': tracker.get('title', folder),
                        'version': tracker.get('version', 'unknown')
                    }
            except:
                pass

    return projects


def fetch_zenodo_remote() -> dict:
    """Fetch Zenodo records using the same query as ZenodoCrawler"""
    remote = {}
    
    # Same query format as ZenodoCrawler._query_zenodo()
    query = (
        "https://zenodo.org/api/records/?"
        "type=dataset&"
        'q=keywords:"canadian-open-neuroscience-platform"'
    )
    
    try:
        print(f"   Zenodo query: {query[:80]}...", flush=True)
        response = requests.get(query, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            hits = data.get('hits', {}).get('hits', [])
            print(f"   Page 1: {len(hits)} records", flush=True)
            
            # Collect all records
            all_records = hits.copy()
            
            # Follow pagination
            next_page = data.get('links', {}).get('next')
            page = 2
            while next_page:
                print(f"   Page {page}: fetching...", end=' ', flush=True)
                next_response = requests.get(next_page, timeout=30)
                if next_response.status_code == 200:
                    next_data = next_response.json()
                    next_hits = next_data.get('hits', {}).get('hits', [])
                    print(f"{len(next_hits)} records", flush=True)
                    all_records.extend(next_hits)
                    next_page = next_data.get('links', {}).get('next')
                    page += 1
                else:
                    print(f"failed (HTTP {next_response.status_code})", flush=True)
                    break
            
            print(f"   Total Zenodo records: {len(all_records)}", flush=True)
            
            for record in all_records:
                metadata = record.get('metadata', {})
                concept_id = metadata.get('conceptrecid')
                if concept_id:
                    remote[concept_id] = {
                        'version': metadata.get('version', 'unknown'),
                        'title': metadata.get('title', ''),
                        'url': f"https://zenodo.org/record/{record.get('id')}",
                        'updated': record.get('updated', '')
                    }
        else:
            print(f"   Zenodo API error: HTTP {response.status_code}", flush=True)
            
    except Exception as e:
        print(f"   Zenodo API error: {e}", flush=True)
    
    return remote


def fetch_osf_remote() -> dict:
    """Fetch OSF records"""
    remote = {}
    
    params = {
        'filter[tags]': 'canadian-open-neuroscience-platform',
        'filter[public]': 'true',
        'page[size]': 100
    }
    
    try:
        print("   Fetching OSF...", flush=True)
        response = requests.get(
            'https://api.osf.io/v2/nodes/',
            params=params,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            nodes = data.get('data', [])
            print(f"   Page 1: {len(nodes)} nodes", flush=True)
            
            all_nodes = nodes.copy()
            
            # Follow pagination
            next_url = data.get('links', {}).get('next')
            page = 2
            while next_url:
                print(f"   Page {page}: fetching...", end=' ', flush=True)
                next_response = requests.get(next_url, timeout=30)
                if next_response.status_code == 200:
                    next_data = next_response.json()
                    next_nodes = next_data.get('data', [])
                    print(f"{len(next_nodes)} nodes", flush=True)
                    all_nodes.extend(next_nodes)
                    next_url = next_data.get('links', {}).get('next')
                    page += 1
                else:
                    print(f"failed", flush=True)
                    break
            
            print(f"   Total OSF records: {len(all_nodes)}", flush=True)
            
            for node in all_nodes:
                attributes = node.get('attributes', {})
                node_id = node.get('id')
                remote[node_id] = {
                    'version': attributes.get('date_modified', ''),
                    'title': attributes.get('title', ''),
                    'url': f"https://osf.io/{node_id}/",
                    'updated': attributes.get('date_modified', '')
                }
        else:
            print(f"   OSF API error: HTTP {response.status_code}", flush=True)
            
    except Exception as e:
        print(f"   OSF API error: {e}", flush=True)
    
    return remote


def main():
    print("=" * 80)
    print("CONP DATASET UPDATE CHECKER")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    user_config = load_config()
    conp_dataset_path = user_config.get('conp-dataset_path', '/data/crawler/conp-dataset')
    projects_dir = os.path.join(conp_dataset_path, 'projects')

    print(f"\nProjects: {projects_dir}")

    # 1. Get local projects
    print("\n1. Reading local trackers...")
    local = get_local_projects_info(projects_dir)
    zenodo_local = [p for p in local.values() if p['type'] == 'zenodo']
    osf_local = [p for p in local.values() if p['type'] == 'osf']
    print(f"   Zenodo projects: {len(zenodo_local)}")
    print(f"   OSF projects: {len(osf_local)}")

    # 2. Fetch remote data
    print("\n2. Fetching remote data...")
    zenodo_remote = fetch_zenodo_remote()
    osf_remote = fetch_osf_remote()

    print(f"\n   Remote summary:")
    print(f"     Zenodo: {len(zenodo_remote)} concepts")
    print(f"     OSF: {len(osf_remote)} nodes")

    # 3. Check for updates
    print("\n3. Checking for updates...")
    updates = []

    # Zenodo updates
    for project in zenodo_local:
        concept_doi = project.get('concept_doi')
        local_version = project.get('version', 'unknown')

        if concept_doi and concept_doi in zenodo_remote:
            remote = zenodo_remote[concept_doi]
            remote_version = remote.get('version', 'unknown')

            if local_version != remote_version:
                updates.append({
                    'folder': project['folder'],
                    'title': project['title'],
                    'source': 'zenodo',
                    'local_version': local_version,
                    'remote_version': remote_version,
                    'concept_doi': concept_doi,
                    'url': remote['url'],
                    'updated': remote['updated']
                })

    # OSF updates (match by title)
    osf_remote_by_title = {v['title']: k for k, v in osf_remote.items()}
    for project in osf_local:
        local_version = project.get('version', 'unknown')
        local_title = project.get('title', '')

        if local_title in osf_remote_by_title:
            node_id = osf_remote_by_title[local_title]
            remote = osf_remote[node_id]
            remote_version = remote.get('version', '')

            if local_version != remote_version:
                updates.append({
                    'folder': project['folder'],
                    'title': project['title'],
                    'source': 'osf',
                    'local_version': local_version,
                    'remote_version': remote_version,
                    'node_id': node_id,
                    'url': remote['url'],
                    'updated': remote['updated']
                })

    # 4. Display results
    print("\n" + "=" * 80)
    if updates:
        print(f"📊 FOUND {len(updates)} DATASET(S) NEEDING UPDATE")
        print("=" * 80)

        for i, u in enumerate(updates, 1):
            print(f"\n[{i}] {u['title']}")
            print(f"    Folder:       {u['folder']}")
            print(f"    Source:       {u['source'].upper()}")
            print(f"    Version:      {u['local_version']} → {u['remote_version']}")
            print(f"    URL:          {u['url']}")
            if u['source'] == 'zenodo':
                print(f"    Concept DOI:  {u['concept_doi']}")
            else:
                print(f"    Node ID:      {u['node_id']}")
            print(f"    Last updated: {u['updated'][:19] if u['updated'] else 'N/A'}")
    else:
        print("✓ ALL DATASETS ARE UP TO DATE")
        print("=" * 80)

    # Summary
    print(f"\n📈 Summary:")
    print(f"    Tracked projects: {len(zenodo_local) + len(osf_local)}")
    print(f"    Need update:      {len(updates)}")
    print(f"    Up to date:       {len(zenodo_local) + len(osf_local) - len(updates)}")


if __name__ == "__main__":
    main()
