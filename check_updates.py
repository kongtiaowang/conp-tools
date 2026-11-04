#!/usr/bin/env python3
"""
check_updates.py - Check for updates to Zenodo/OSF datasets
Reads DATS.json files to get project information
"""

import os
import json
import requests
import re
from datetime import datetime
import time

import sys
sys.path.insert(0, '/data/crawler/conp-dataset')


def load_config():
    """Load configuration from user's config file"""
    config_path = os.path.expanduser("~/.conp_crawler_config.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}


def extract_id_from_identifier(identifier_str):
    """
    Extract ID from various identifier formats
    
    Examples:
    - "10.5281/zenodo.12345" -> "12345"
    - "https://zenodo.org/record/12345" -> "12345"
    - "https://zenodo.org/records/12345" -> "12345"
    - "https://osf.io/abcde/" -> "abcde"
    - "osf.io/j532r/" -> "j532r"
    - "Open Science Framework (osf.io/j532r/)" -> "j532r"
    - "doi:10.5281/zenodo.12345" -> "12345"
    """
    if not identifier_str:
        return None
    
    identifier_str = str(identifier_str)
    
    # Extract from Zenodo URL
    if 'zenodo.org' in identifier_str:
        match = re.search(r'/(?:record|records|doi)/(?:10\.5281/zenodo\.)?(\d+)', identifier_str)
        if match:
            return match.group(1)
    
    # Extract from OSF URL or text
    if 'osf.io' in identifier_str or 'osf.io/' in identifier_str:
        match = re.search(r'osf\.io/([a-zA-Z0-9]{5,})', identifier_str)
        if match:
            return match.group(1)
        match = re.search(r'osf\.io/([a-zA-Z0-9]+)', identifier_str)
        if match:
            return match.group(1)
    
    # Extract from DOI
    if '10.5281/zenodo.' in identifier_str:
        parts = identifier_str.split('zenodo.')
        if len(parts) > 1:
            return re.sub(r'[^0-9]', '', parts[1])
    
    # If it's just numbers, return as is
    if identifier_str.isdigit():
        return identifier_str
    
    # If it's alphanumeric and looks like an OSF ID (5+ characters)
    if re.match(r'^[a-zA-Z0-9]{5,}$', identifier_str):
        return identifier_str
    
    return None


def get_local_projects_info(projects_dir: str) -> dict:
    """
    Get local project information from DATS.json files
    """
    projects = {}

    if not os.path.exists(projects_dir):
        print(f"Warning: projects directory does not exist: {projects_dir}")
        return projects

    for folder in os.listdir(projects_dir):
        folder_path = os.path.join(projects_dir, folder)
        if not os.path.isdir(folder_path):
            continue

        dats_file = os.path.join(folder_path, "DATS.json")
        if not os.path.exists(dats_file):
            continue
            
        try:
            content = None
            for encoding in ['utf-8', 'latin-1', 'cp1252']:
                try:
                    with open(dats_file, 'r', encoding=encoding) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
                continue
                
            dats = json.loads(content)
            
            title = dats.get('title', folder)
            version = dats.get('version', 'unknown')
            
            zenodo_id = None
            osf_id = None
            
            # Check identifiers field
            identifiers = dats.get('identifiers', [])
            for identifier in identifiers:
                id_value = identifier.get('identifier', '')
                id_source = identifier.get('identifierSource', '').lower()
                
                if 'zenodo' in id_source or 'zenodo' in id_value.lower():
                    extracted = extract_id_from_identifier(id_value)
                    if extracted:
                        zenodo_id = extracted
                elif 'osf' in id_source or 'osf.io' in id_value.lower() or 'osf' in id_value.lower():
                    extracted = extract_id_from_identifier(id_value)
                    if extracted:
                        osf_id = extracted
                
                id_type = identifier.get('type', {}).get('value', '').lower()
                if id_type == 'zenodo' or 'zenodo' in id_type:
                    extracted = extract_id_from_identifier(id_value)
                    if extracted:
                        zenodo_id = extracted
                elif id_type == 'osf' or 'osf' in id_type:
                    extracted = extract_id_from_identifier(id_value)
                    if extracted:
                        osf_id = extracted
            
            # Check extraProperties for OSF node ID
            extra_properties = dats.get('extraProperties', [])
            for prop in extra_properties:
                category = prop.get('category', '').lower()
                if category == 'osf_node_id' or category == 'osf':
                    values = prop.get('values', [])
                    for val in values:
                        osf_id = val.get('value', '')
                        if osf_id:
                            break
                    if osf_id:
                        break
            
            # Check distributions
            if not osf_id:
                distributions = dats.get('distributions', [])
                for dist in distributions:
                    access = dist.get('access', {})
                    landing_page = access.get('landingPage', '')
                    if landing_page:
                        if 'osf.io' in landing_page.lower():
                            extracted = extract_id_from_identifier(landing_page)
                            if extracted:
                                osf_id = extracted
                                break
                        elif 'zenodo' in landing_page.lower():
                            extracted = extract_id_from_identifier(landing_page)
                            if extracted:
                                zenodo_id = extracted
                    
                    access_url = access.get('accessUrl', [])
                    if isinstance(access_url, list):
                        for url in access_url:
                            if 'osf.io' in url.lower():
                                extracted = extract_id_from_identifier(url)
                                if extracted:
                                    osf_id = extracted
                                    break
                            elif 'zenodo' in url.lower():
                                extracted = extract_id_from_identifier(url)
                                if extracted:
                                    zenodo_id = extracted
                        if osf_id:
                            break
            
            if 'doi' in dats:
                doi = dats.get('doi', '')
                if 'zenodo' in doi.lower():
                    extracted = extract_id_from_identifier(doi)
                    if extracted:
                        zenodo_id = extracted
            
            if zenodo_id:
                projects[f"{folder}_zenodo"] = {
                    'type': 'zenodo',
                    'folder': folder,
                    'title': title,
                    'concept_id': str(zenodo_id),
                    'version': str(version) if version else 'unknown'
                }
            
            if osf_id:
                projects[f"{folder}_osf"] = {
                    'type': 'osf',
                    'folder': folder,
                    'title': title,
                    'node_id': str(osf_id),
                    'version': str(version) if version else 'unknown'
                }
                
        except Exception as e:
            print(f"   Error reading {dats_file}: {e}")

    return projects


def fetch_zenodo_remote_by_ids(concept_ids: list) -> dict:
    """
    Fetch Zenodo records by concept IDs
    Handles both conceptrecid and record IDs
    """
    remote = {}
    
    clean_ids = set()
    for cid in concept_ids:
        if not cid:
            continue
        
        clean_id = str(cid)
        if 'zenodo.org' in clean_id:
            match = re.search(r'/(?:record|records|doi)/(?:10\.5281/zenodo\.)?(\d+)', clean_id)
            if match:
                clean_id = match.group(1)
            else:
                continue
        
        clean_id = re.sub(r'[^0-9]', '', clean_id)
        if clean_id and clean_id.isdigit():
            clean_ids.add(clean_id)
    
    print(f"   Fetching {len(clean_ids)} Zenodo concepts...", flush=True)
    
    found_count = 0
    
    for concept_id in clean_ids:
        try:
            # Query for latest version using conceptrecid
            url = f"https://zenodo.org/api/records/?q=conceptrecid:{concept_id}&sort=version&size=1"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                hits = data.get('hits', {}).get('hits', [])
                
                if hits:
                    record = hits[0]
                    metadata = record.get('metadata', {})
                    record_id = record.get('id')
                    
                    remote[concept_id] = {
                        'version': metadata.get('version') or record.get('updated', ''),
                        'title': metadata.get('title', ''),
                        'url': f"https://zenodo.org/record/{record_id}",
                        'updated': record.get('updated', ''),
                        'record_id': str(record_id)
                    }
                    found_count += 1
                    print(f"     Found concept {concept_id} (latest: {record_id})", flush=True)
                    continue
                else:
                    # No hits - try direct fetch (maybe it's a record ID)
                    direct_url = f"https://zenodo.org/api/records/{concept_id}"
                    direct_response = requests.get(direct_url, timeout=10)
                    
                    if direct_response.status_code == 200:
                        record = direct_response.json()
                        metadata = record.get('metadata', {})
                        record_id = record.get('id')
                        
                        remote[concept_id] = {
                            'version': metadata.get('version') or record.get('updated', ''),
                            'title': metadata.get('title', ''),
                            'url': f"https://zenodo.org/record/{record_id}",
                            'updated': record.get('updated', ''),
                            'record_id': str(record_id)
                        }
                        found_count += 1
                        print(f"     Found record {concept_id} (direct)", flush=True)
                        continue
            
            elif response.status_code == 429:
                print(f"     Rate limited, waiting...", flush=True)
                time.sleep(3)
                # Retry
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    hits = data.get('hits', {}).get('hits', [])
                    if hits:
                        record = hits[0]
                        metadata = record.get('metadata', {})
                        record_id = record.get('id')
                        remote[concept_id] = {
                            'version': metadata.get('version') or record.get('updated', ''),
                            'title': metadata.get('title', ''),
                            'url': f"https://zenodo.org/record/{record_id}",
                            'updated': record.get('updated', ''),
                            'record_id': str(record_id)
                        }
                        found_count += 1
                        print(f"     Found concept {concept_id} (after retry)", flush=True)
            
            if concept_id not in remote:
                print(f"     Not found: {concept_id}", flush=True)
            
            time.sleep(0.2)
            
        except Exception as e:
            print(f"     Error fetching {concept_id}: {e}", flush=True)
    
    print(f"\n   Fetched {found_count} Zenodo records", flush=True)
    return remote


def fetch_osf_remote_by_ids(node_ids: list) -> dict:
    """Fetch OSF records by node IDs"""
    remote = {}
    
    clean_ids = set()
    for nid in node_ids:
        if not nid:
            continue
        
        clean_id = str(nid).strip()
        if 'osf.io' in clean_id:
            match = re.search(r'osf\.io/([a-zA-Z0-9]+)', clean_id)
            if match:
                clean_id = match.group(1)
            else:
                continue
        
        clean_id = re.sub(r'[^a-zA-Z0-9]', '', clean_id)
        if clean_id and len(clean_id) >= 5:
            clean_ids.add(clean_id)
    
    print(f"   Fetching {len(clean_ids)} OSF nodes...", flush=True)
    
    for node_id in clean_ids:
        try:
            url = f"https://api.osf.io/v2/nodes/{node_id}/"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                node = data.get('data', {})
                attributes = node.get('attributes', {})
                
                remote[node_id] = {
                    'version': attributes.get('date_modified', ''),
                    'title': attributes.get('title', ''),
                    'url': f"https://osf.io/{node_id}/",
                    'updated': attributes.get('date_modified', '')
                }
                print(f"     Found: {node_id}", flush=True)
            else:
                print(f"     Not found: {node_id} (HTTP {response.status_code})", flush=True)
            
            time.sleep(0.1)
        except Exception as e:
            print(f"     Error fetching {node_id}: {e}", flush=True)
    
    print(f"   Fetched {len(remote)} OSF records", flush=True)
    return remote


def main():
    """Main execution function"""
    print("=" * 80)
    print("CONP DATASET UPDATE CHECKER")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    user_config = load_config()
    conp_dataset_path = user_config.get('conp-dataset_path', '/data/crawler/conp-dataset')
    projects_dir = os.path.join(conp_dataset_path, 'projects')

    print(f"\nProjects: {projects_dir}")

    # 1. Get local projects from DATS.json
    print("\n1. Reading local DATS.json files...")
    local = get_local_projects_info(projects_dir)
    zenodo_local = [p for p in local.values() if p['type'] == 'zenodo']
    osf_local = [p for p in local.values() if p['type'] == 'osf']
    print(f"   Zenodo projects: {len(zenodo_local)}")
    print(f"   OSF projects: {len(osf_local)}")

    zenodo_concept_ids = [p.get('concept_id') for p in zenodo_local if p.get('concept_id')]
    osf_node_ids = [p.get('node_id') for p in osf_local if p.get('node_id')]

    # 2. Fetch remote data
    print("\n2. Fetching remote data...")
    
    if zenodo_concept_ids:
        zenodo_remote = fetch_zenodo_remote_by_ids(zenodo_concept_ids)
    else:
        zenodo_remote = {}
        print("   No Zenodo concepts to fetch")
    
    if osf_node_ids:
        osf_remote = fetch_osf_remote_by_ids(osf_node_ids)
    else:
        osf_remote = {}
        print("   No OSF nodes to fetch")

    print(f"\n   Remote summary:")
    print(f"     Zenodo: {len(zenodo_remote)} records")
    print(f"     OSF: {len(osf_remote)} nodes")

    # 3. Check for updates
    print("\n3. Checking for updates...")
    updates = []

    # Check Zenodo
    zenodo_found = 0
    zenodo_not_found = 0
    
    for project in zenodo_local:
        concept_id = project.get('concept_id')
        local_version = project.get('version', 'unknown')

        if not concept_id:
            continue

        clean_id = str(concept_id)
        if 'zenodo.org' in clean_id:
            match = re.search(r'/(?:record|records|doi)/(?:10\.5281/zenodo\.)?(\d+)', clean_id)
            if match:
                clean_id = match.group(1)
            else:
                continue
        clean_id = re.sub(r'[^0-9]', '', clean_id)

        found = False
        for remote_id, remote_data in zenodo_remote.items():
            if remote_id == clean_id or remote_data.get('record_id') == clean_id:
                found = True
                remote_version = remote_data.get('version', 'unknown')
                if local_version != remote_version:
                    updates.append({
                        'folder': project['folder'],
                        'title': project['title'],
                        'source': 'zenodo',
                        'local_version': local_version,
                        'remote_version': remote_version,
                        'concept_id': clean_id,
                        'url': remote_data['url'],
                        'updated': remote_data['updated']
                    })
                zenodo_found += 1
                break
        
        if not found:
            zenodo_not_found += 1

    # Check OSF
    osf_found = 0
    osf_not_found = 0
    
    for project in osf_local:
        node_id = project.get('node_id')
        local_version = project.get('version', 'unknown')

        if not node_id:
            continue

        clean_id = str(node_id)
        if 'osf.io' in clean_id:
            match = re.search(r'osf\.io/([a-zA-Z0-9]+)', clean_id)
            if match:
                clean_id = match.group(1)
            else:
                continue
        clean_id = re.sub(r'[^a-zA-Z0-9]', '', clean_id)

        if clean_id in osf_remote:
            osf_found += 1
            remote = osf_remote[clean_id]
            remote_version = remote.get('version', '')

            if local_version != remote_version:
                updates.append({
                    'folder': project['folder'],
                    'title': project['title'],
                    'source': 'osf',
                    'local_version': local_version,
                    'remote_version': remote_version,
                    'node_id': clean_id,
                    'url': remote['url'],
                    'updated': remote['updated']
                })
        else:
            osf_not_found += 1

    print(f"\n   Fetch statistics:")
    print(f"     Zenodo: {zenodo_found} found, {zenodo_not_found} not found")
    print(f"     OSF: {osf_found} found, {osf_not_found} not found")

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
                print(f"    Concept ID:   {u['concept_id']}")
            else:
                print(f"    Node ID:      {u['node_id']}")
            print(f"    Last updated: {u['updated'][:19] if u['updated'] else 'N/A'}")
    else:
        print("✓ ALL DATASETS ARE UP TO DATE")
        print("=" * 80)

    total_projects = len(zenodo_local) + len(osf_local)
    print(f"\n📈 Summary:")
    print(f"    Tracked projects: {total_projects}")
    print(f"    Need update:      {len(updates)}")
    print(f"    Up to date:       {total_projects - len(updates)}")

    if updates:
        log_dir = os.path.join(conp_dataset_path, 'log')
        save_update_report(updates, log_dir)


def save_update_report(updates, log_dir):
    """Save update report to JSON file"""
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = os.path.join(log_dir, f"dataset_updates_{timestamp}.json")
    
    report = {
        'timestamp': datetime.now().isoformat(),
        'summary': {
            'need_update': len(updates)
        },
        'new_datasets': updates
    }
    
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\n✓ Update report saved: {report_file}")


if __name__ == "__main__":
    main()
