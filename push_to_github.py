#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import json
import urllib.request
from typing import Optional

def run(cmd: list[str], cwd: str | None = None, capture_output: bool = False, check: bool = True):
    """Run a command and return the result."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=capture_output, text=True)
    if check and result.returncode != 0:
        if capture_output:
            print(f"Error running {' '.join(cmd)}: {result.stderr}")
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result

def clean_title(title: str) -> str:
    """Safe title for folder/repo names."""
    clean = re.sub(r'[<>:"/\\|?*]', '_', title)
    clean = re.sub(r'\s+', '_', clean)
    clean = re.sub(r'_+', '_', clean)
    clean = clean.strip('_')
    return clean

def find_dataset_dir(basedir: str, record_id: str) -> Optional[str]:
    """Find the dataset directory containing the record ID."""
    projects_dir = os.path.join(basedir, "projects")
    if not os.path.exists(projects_dir):
        return None
    
    for folder in os.listdir(projects_dir):
        folder_path = os.path.join(projects_dir, folder)
        if not os.path.isdir(folder_path):
            continue
            
        # Check OSF tracker
        config_path = os.path.join(folder_path, ".conp-osf-crawler.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    stored_id = config.get("node_id")
                    if str(stored_id) == str(record_id):
                        return folder_path
            except:
                pass
        
        # Check Zenodo tracker
        config_path = os.path.join(folder_path, ".conp-zenodo-crawler.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    stored_id = config.get("concept_id") or config.get("record_id")
                    if str(stored_id) == str(record_id):
                        return folder_path
            except:
                pass
        
        # Check DATS.json
        dats_path = os.path.join(folder_path, "DATS.json")
        if os.path.exists(dats_path):
            try:
                with open(dats_path, 'r') as f:
                    dats = json.load(f)
                    # Look for OSF ID
                    extra_props = dats.get('extraProperties', [])
                    for prop in extra_props:
                        if prop.get('category') == 'osf_node_id':
                            values = prop.get('values', [])
                            for val in values:
                                if str(val.get('value')) == str(record_id):
                                    return folder_path
                    
                    # Look for Zenodo ID
                    identifiers = dats.get('identifiers', [])
                    for identifier in identifiers:
                        id_value = identifier.get('identifier', '')
                        if str(record_id) in id_value:
                            return folder_path
            except:
                pass
    
    return None

def find_repo_by_id_on_github(org: str, record_id: str) -> Optional[str]:
    """
    在 GitHub 上搜索 conp-bot 的所有仓库，查找包含该 record_id 的仓库
    通过检查每个仓库的 .conp-*-crawler.json 或 DATS.json
    """
    print(f"   🔍 Searching GitHub for record ID: {record_id}...")
    
    try:
        # 获取所有 conp-bot 的仓库
        result = run(["gh", "repo", "list", org, "--limit", "100", "--json", "name"], capture_output=True)
        repos = json.loads(result.stdout)
        
        print(f"   Found {len(repos)} repositories in {org}")
        
        for repo in repos:
            repo_name = repo['name']
            
            # 跳过不是 conp-dataset- 开头的仓库
            if not repo_name.startswith("conp-dataset-"):
                continue
            
            # 尝试从仓库中读取 tracker 文件
            # 方法1: 通过 GitHub API 获取 .conp-osf-crawler.json
            api_url = f"https://api.github.com/repos/{org}/{repo_name}/contents/.conp-osf-crawler.json"
            try:
                req = urllib.request.Request(api_url)
                req.add_header('Accept', 'application/vnd.github.v3+json')
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode())
                        content = data.get('content', '')
                        if content:
                            # Decode base64
                            import base64
                            content = base64.b64decode(content).decode('utf-8')
                            tracker = json.loads(content)
                            node_id = tracker.get('node_id')
                            if str(node_id) == str(record_id):
                                print(f"   ✅ Found OSF ID {record_id} in repo: {repo_name}")
                                return repo_name
            except:
                pass
            
            # 方法2: 检查 Zenodo tracker
            api_url = f"https://api.github.com/repos/{org}/{repo_name}/contents/.conp-zenodo-crawler.json"
            try:
                req = urllib.request.Request(api_url)
                req.add_header('Accept', 'application/vnd.github.v3+json')
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode())
                        content = data.get('content', '')
                        if content:
                            import base64
                            content = base64.b64decode(content).decode('utf-8')
                            tracker = json.loads(content)
                            # 检查 concept_id 或 record_id
                            concept_id = tracker.get('concept_id')
                            record_id_tracker = tracker.get('record_id')
                            if str(concept_id) == str(record_id) or str(record_id_tracker) == str(record_id):
                                print(f"   ✅ Found Zenodo ID {record_id} in repo: {repo_name}")
                                return repo_name
            except:
                pass
            
            # 方法3: 检查 DATS.json
            api_url = f"https://api.github.com/repos/{org}/{repo_name}/contents/DATS.json"
            try:
                req = urllib.request.Request(api_url)
                req.add_header('Accept', 'application/vnd.github.v3+json')
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode())
                        content = data.get('content', '')
                        if content:
                            import base64
                            content = base64.b64decode(content).decode('utf-8')
                            dats = json.loads(content)
                            
                            # 检查 OSF ID
                            extra_props = dats.get('extraProperties', [])
                            for prop in extra_props:
                                if prop.get('category') == 'osf_node_id':
                                    values = prop.get('values', [])
                                    for val in values:
                                        if str(val.get('value')) == str(record_id):
                                            print(f"   ✅ Found OSF ID {record_id} in DATS.json of repo: {repo_name}")
                                            return repo_name
                            
                            # 检查 Zenodo ID
                            identifiers = dats.get('identifiers', [])
                            for identifier in identifiers:
                                id_value = identifier.get('identifier', '')
                                if str(record_id) in id_value:
                                    print(f"   ✅ Found Zenodo ID {record_id} in DATS.json of repo: {repo_name}")
                                    return repo_name
            except:
                pass
        
        print(f"   ❌ No existing repo found for record ID: {record_id}")
        return None
        
    except Exception as e:
        print(f"   ⚠️ Error searching GitHub: {e}")
        return None

def get_repo_name(folder_name: str, record_id: str, org: str = "conp-bot") -> str:
    """
    Get GitHub repository name.
    Priority:
    1. Find existing repo by ID on GitHub
    2. Auto-generate from folder name
    """
    
    # 1. 在 GitHub 上查找包含此 ID 的现有仓库
    existing_repo = find_repo_by_id_on_github(org, record_id)
    if existing_repo:
        print(f"   📦 Using existing repo: {existing_repo}")
        return existing_repo
    
    # 2. 自动生成新仓库名
    print(f"   🆕 No existing repo found. Creating new repo from folder name...")
    name = folder_name.removeprefix("conp-dataset-")
    name = name.split('(')[0].strip('_')
    name = name.replace('&', 'and')
    name = name.replace(',', '')
    name = name.replace(' ', '_')
    name = re.sub(r'_+', '_', name)
    name = f"conp-dataset-{name}"
    if len(name) > 80:
        name = name[:80].strip('_')
    return name

def update_existing_repo(dataset_dir: str, repo_name: str, org: str, dry_run: bool):
    """Update an existing GitHub repository with latest changes"""
    print(f"\n📦 Updating existing repository: {org}/{repo_name}")
    
    if dry_run:
        print(f"Would update: {dataset_dir}")
        print(f"Would push to: https://github.com/{org}/{repo_name}.git")
        return
    
    # Ensure we have the remote
    try:
        run(["git", "remote", "get-url", "origin"], cwd=dataset_dir, capture_output=True)
    except subprocess.CalledProcessError:
        repo_url = f"https://github.com/{org}/{repo_name}.git"
        run(["git", "remote", "add", "origin", repo_url], cwd=dataset_dir)
    
    # Check if repo exists on GitHub
    try:
        run(["gh", "repo", "view", f"{org}/{repo_name}"], capture_output=True)
        print(f"✅ Repository {org}/{repo_name} exists")
    except subprocess.CalledProcessError:
        print(f"❌ Repository {org}/{repo_name} does not exist!")
        print(f"   Creating new repository...")
        run(["gh", "repo", "create", f"{org}/{repo_name}", "--public", "--confirm"])
    
    # Get current branch
    try:
        branch_result = run(["git", "symbolic-ref", "--short", "HEAD"], cwd=dataset_dir, capture_output=True)
        current_branch = branch_result.stdout.strip()
    except:
        current_branch = "master"
    
    # Add all changes
    print("📝 Adding changes...")
    run(["git", "add", "."], cwd=dataset_dir)
    
    # Check if there are changes to commit
    status_result = run(["git", "status", "--porcelain"], cwd=dataset_dir, capture_output=True)
    if status_result.stdout.strip():
        print("📝 Committing changes...")
        run(["git", "commit", "-m", "Update dataset from OSF/Zenodo", "--no-verify"], cwd=dataset_dir)
        
        # Push to GitHub
        print(f"🚀 Pushing to {org}/{repo_name}...")
        run(["git", "push", "-u", "origin", current_branch, "--force"], cwd=dataset_dir)
        
        # Also push git-annex if it exists
        try:
            run(["git", "push", "origin", "git-annex", "--force"], cwd=dataset_dir)
        except:
            print("   No git-annex branch to push")
        
        print(f"✅ Successfully updated {org}/{repo_name}")
    else:
        print("ℹ️  No changes to commit")

def create_new_repo(dataset_dir: str, repo_name: str, org: str, dry_run: bool):
    """Create a new GitHub repository and push dataset"""
    print(f"\n📦 Creating new repository: {org}/{repo_name}")
    
    if dry_run:
        print(f"Would create: https://github.com/{org}/{repo_name}.git")
        print(f"Would push from: {dataset_dir}")
        return
    
    repo_url = f"https://github.com/{org}/{repo_name}.git"
    try:
        run(["gh", "repo", "view", f"{org}/{repo_name}"], capture_output=True)
        print(f"✅ Repository {org}/{repo_name} already exists")
    except subprocess.CalledProcessError:
        print(f"➕ Creating new repository: {org}/{repo_name}...")
        run(["gh", "repo", "create", f"{org}/{repo_name}", "--public", "--confirm"])
    
    # Update remote
    run(["git", "remote", "remove", "origin"], cwd=dataset_dir, check=False)
    run(["git", "remote", "add", "origin", repo_url], cwd=dataset_dir)
    
    # Push branches
    try:
        branch_result = run(["git", "symbolic-ref", "--short", "HEAD"], cwd=dataset_dir, capture_output=True)
        current_branch = branch_result.stdout.strip()
    except:
        current_branch = "master"
    
    print(f"🚀 Pushing {current_branch} branch...")
    run(["git", "push", "-u", "--force", "origin", current_branch], cwd=dataset_dir)
    
    print("🚀 Pushing git-annex branch...")
    try:
        run(["git", "push", "--force", "origin", "git-annex"], cwd=dataset_dir)
    except subprocess.CalledProcessError:
        print("   No git-annex branch to push")

def create_pull_request(main_repo_path: str, dataset_dir: str, repo_url: str, repo_name: str, org: str, record_id: str, dry_run: bool, is_update: bool = False):
    """Add dataset as submodule on a new branch and create a PR."""
    folder_name = os.path.basename(dataset_dir)
    relative_path = os.path.join("projects", folder_name)
    
    prefix = "update-dataset" if is_update else "add-dataset"
    branch_name = f"{prefix}-{record_id}"
    
    clean_title = repo_name.replace("conp-dataset-", "").replace("_", " ")
    
    print(f"\n🔗 Integrating dataset into main repository using branch {branch_name}...")
    
    if dry_run:
        print(f"Would create branch: {branch_name}")
        print(f"Would update submodule: {relative_path}")
        print(f"Would commit: {'Update' if is_update else 'Add'} dataset: {clean_title}")
        return
    
    # Clean up broken paths
    broken_paths = ["projects/cneuromod_processed"]
    for bp in broken_paths:
        bp_path = os.path.join(main_repo_path, bp)
        if os.path.lexists(bp_path):
            print(f"🧹 Cleanup: Removing corrupted submodule path: {bp}")
            try:
                if os.path.isdir(bp_path) and not os.path.islink(bp_path):
                    import shutil
                    shutil.rmtree(bp_path)
                else:
                    os.remove(bp_path)
            except Exception as e:
                print(f"⚠️  Could not remove {bp}: {e}")
    
    # Sync with upstream
    print("🔄 Syncing main repository...")
    try:
        run(["git", "remote", "get-url", "upstream"], cwd=main_repo_path)
        upstream_remote = "upstream"
    except subprocess.CalledProcessError:
        upstream_remote = "origin"
    
    run(["git", "fetch", upstream_remote], cwd=main_repo_path)
    run(["git", "checkout", "--no-recurse-submodules", "-f", "master"], cwd=main_repo_path)
    run(["git", "reset", "--hard", f"{upstream_remote}/master"], cwd=main_repo_path)
    run(["git", "clean", "-fd"], cwd=main_repo_path)
    
    # Create or switch to branch
    print(f"🌿 Switching to branch {branch_name}...")
    try:
        run(["git", "checkout", "--no-recurse-submodules", "-B", branch_name], cwd=main_repo_path)
    except subprocess.CalledProcessError:
        run(["git", "checkout", branch_name], cwd=main_repo_path)
    
    # Update or add submodule
    print(f"📦 {'Updating' if is_update else 'Adding'} submodule at {relative_path}...")
    
    # Check if submodule already exists
    submodule_exists = False
    try:
        result = run(["git", "submodule", "status", relative_path], cwd=main_repo_path, capture_output=True, check=False)
        if result.returncode == 0:
            submodule_exists = True
    except:
        pass
    
    if submodule_exists or is_update:
        # Update existing submodule
        run(["git", "submodule", "update", "--init", "--recursive", relative_path], cwd=main_repo_path, check=False)
        run(["git", "add", relative_path], cwd=main_repo_path)
    else:
        # Add as new submodule
        run(["git", "submodule", "add", "--force", repo_url, relative_path], cwd=main_repo_path)
    
    # Commit
    commit_msg = f"{'Update' if is_update else 'Add'} dataset: {clean_title}"
    try:
        run(["git", "commit", "-m", commit_msg, "--no-verify"], cwd=main_repo_path)
    except subprocess.CalledProcessError:
        print("ℹ️  Nothing to commit.")
    
    # Push branch
    print(f"🚀 Pushing branch {branch_name}...")
    run(["git", "push", "-f", "-u", "origin", branch_name], cwd=main_repo_path)
    
    # Create PR
    print("📝 Creating Pull Request...")
    pr_type = "Update" if is_update else "Add"
    pr_title = f"{pr_type} dataset: {clean_title}"
    try:
        run([
            "gh", "pr", "create", 
            "--repo", "CONP-PCNO/conp-dataset", 
            "--base", "master", 
            "--head", f"{org}:{branch_name}", 
            "--title", pr_title, 
            "--body", f"Automated {pr_type.lower()} of dataset {clean_title} from {repo_url}"
        ], cwd=main_repo_path)
    except subprocess.CalledProcessError as e:
        print(f"⚠️  PR creation failed: {e}. It might already exist.")
    
    # Switch back to master
    print("🏠 Switching back to master branch...")
    run(["git", "checkout", "master"], cwd=main_repo_path)

def main():
    parser = argparse.ArgumentParser(description="Push an imported dataset to GitHub and optionally create a PR.")
    parser.add_argument("--record", required=True, help="Record ID or path to search for")
    parser.add_argument("--basedir", default=".", help="Base directory where 'projects' folder is located")
    parser.add_argument("--main-repo", help="Path to the main conp-dataset repository")
    parser.add_argument("--org", default="conp-bot", help="GitHub organization/user to push to")
    parser.add_argument("--pr", action="store_true", help="Whether to create a Pull Request to CONP-PCNO/conp-dataset")
    parser.add_argument("--update", action="store_true", help="Whether this is an update to an existing dataset")
    parser.add_argument("--zenodo-token", help="Zenodo API token (optional)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without executing")
    args = parser.parse_args()

    record_id = args.record.split("/")[-1]
    
    search_dir = args.basedir
    if args.main_repo and args.basedir == ".":
        search_dir = args.main_repo
        
    print(f"🔍 Searching for dataset with record ID: {record_id} in {search_dir}/projects...")
    dataset_dir = find_dataset_dir(search_dir, record_id)
    
    if not dataset_dir:
        print(f"❌ Error: Could not find dataset directory for record {record_id}")
        return

    folder_name = os.path.basename(dataset_dir)
    
    # 获取 repo 名称：先在 GitHub 上查找包含该 ID 的现有仓库
    repo_name = get_repo_name(folder_name, record_id, args.org)
    repo_url = f"https://github.com/{args.org}/{repo_name}.git"
    
    print(f"📂 Found dataset at: {dataset_dir}")
    print(f"🏷️  Repo name: {repo_name}")
    print(f"🔗 Target URL: {repo_url}")
    
    # Check if this is an update or new dataset
    if args.update:
        print(f"\n🔄 UPDATE MODE: Updating existing dataset")
        update_existing_repo(dataset_dir, repo_name, args.org, args.dry_run)
    else:
        print(f"\n➕ NEW DATASET MODE: Adding new dataset")
        create_new_repo(dataset_dir, repo_name, args.org, args.dry_run)
    
    # Handle PR workflow
    if args.pr:
        main_repo_path = args.main_repo or os.path.abspath(args.basedir)
        create_pull_request(main_repo_path, dataset_dir, repo_url, repo_name, args.org, record_id, args.dry_run, args.update)

    print(f"\n✨ Success! Workflow complete.")

if __name__ == "__main__":
    main()
