#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import json
import urllib.request
from typing import Optional

def run(cmd: list[str], cwd: str | None = None, capture_output: bool = False):
    """Run a command and return the result."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=capture_output, text=True)
    if result.returncode != 0:
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
            
        # Check for crawler config file
        config_path = os.path.join(folder_path, ".conp-zenodo-crawler.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    if str(config.get("record_id")) == str(record_id):
                        return folder_path
            except:
                pass
    return None

def get_repo_name(folder_name: str) -> str:
    """
    Generate a GitHub repository name from the folder name.
    Always adds 'conp-dataset-' prefix for the GitHub repo.
    Sanitizes unsafe characters and truncates to 80 chars.
    """
    # Strip any existing conp-dataset- prefix first to avoid double-prefixing
    name = folder_name.removeprefix("conp-dataset-")
    # Remove everything after the first parenthesis if present
    name = name.split('(')[0].strip('_')
    # Replace problematic characters with safe alternatives
    name = name.replace('&', 'and')
    name = name.replace(',', '')
    name = name.replace(' ', '_')
    # Collapse multiple underscores
    name = re.sub(r'_+', '_', name)
    # Add the conp-dataset- prefix for GitHub repo name
    name = f"conp-dataset-{name}"
    # Truncate to a reasonable length
    if len(name) > 80:
        name = name[:80].strip('_')
    return name

def create_pull_request(main_repo_path: str, dataset_dir: str, repo_url: str, repo_name: str, org: str, record_id: str, dry_run: bool):
    """Add dataset as submodule on a new branch and create a PR."""
    folder_name = os.path.basename(dataset_dir)
    relative_path = os.path.join("projects", folder_name)
    
    # Use a unique branch name for this dataset
    branch_name = f"add-dataset-{record_id}"
    
    # Try to extract a clean title for the commit message
    clean_title = repo_name.replace("conp-dataset-", "").replace("_", " ")
    
    print(f"\n🔗 Integrating dataset into main repository at {main_repo_path} using branch {branch_name}...")
    
    if dry_run:
        print(f"Would create branch: {branch_name}")
        print(f"Would run: git submodule add {repo_url} {relative_path}")
        print(f"Would commit: Add dataset: {clean_title}")
        print(f"Would push to: {branch_name}")
        print(f"Would run: gh pr create --repo CONP-PCNO/conp-dataset --base master --head {org}:{branch_name} ...")
        return

    # Ensure the main repository is up‑to‑date with upstream (or origin) before branching
    print("🔄 Syncing main repository with upstream/master ...")
    # If an upstream remote exists, fetch from it; otherwise fetch from origin
    try:
        run(["git", "remote", "get-url", "upstream"], cwd=main_repo_path)
        upstream_exists = True
    except subprocess.CalledProcessError:
        upstream_exists = False
    if upstream_exists:
        run(["git", "fetch", "upstream"], cwd=main_repo_path)
        run(["git", "checkout", "master"], cwd=main_repo_path)
        run(["git", "reset", "--hard", "upstream/master"], cwd=main_repo_path)
    else:
        # Fallback: pull from origin master
        run(["git", "checkout", "master"], cwd=main_repo_path)
        run(["git", "pull", "origin", "master"], cwd=main_repo_path)

    # 0. Create & switch to the new branch (based on the freshly synced master)
    print(f"🌿 Creating branch {branch_name} ...")
    try:
        run(["git", "checkout", "-b", branch_name], cwd=main_repo_path)
    except subprocess.CalledProcessError:
        # If the branch already exists, just checkout it
        print(f"⚠️ Branch {branch_name} already exists, checking out ...")
        run(["git", "checkout", branch_name], cwd=main_repo_path)


    # 1. Add submodule
    print(f"➕ Adding submodule at {relative_path}...")
    try:
        run(["git", "submodule", "add", repo_url, relative_path], cwd=main_repo_path)
    except subprocess.CalledProcessError:
        print("⚠️  Submodule add failed. Trying to add files directly...")
        run(["git", "add", ".gitmodules", relative_path], cwd=main_repo_path)

    # 2. Commit
    print("📝 Committing changes...")
    commit_msg = f"Add dataset: {clean_title}"
    try:
        run(["git", "commit", "-m", commit_msg, "--no-verify"], cwd=main_repo_path)
    except subprocess.CalledProcessError:
        print("ℹ️  Nothing to commit.")

    # 3. Push to fork using the new branch
    print(f"🚀 Pushing to fork branch {branch_name}...")
    run(["git", "push", "-u", "origin", branch_name], cwd=main_repo_path)

    # 4. Create PR
    print("📝 Creating Pull Request on GitHub...")
    pr_title = f"Add dataset: {clean_title}"
    pr_body = f"New dataset added as submodule: {repo_name}\n\nAutomatically generated by CONP-Zenodo-Crawler."
    
    try:
        run([
            "gh", "pr", "create", 
            "--repo", "CONP-PCNO/conp-dataset", 
            "--base", "master", 
            "--head", f"{org}:{branch_name}", 
            "--title", pr_title, 
            "--body", pr_body
        ], cwd=main_repo_path)
    except subprocess.CalledProcessError as e:
        print(f"⚠️  PR creation failed: {e}. It might already exist.")
    
    # Switch back to master
    print("🏠 Switching back to master branch...")
    run(["git", "checkout", "master"], cwd=main_repo_path)

def main():
    parser = argparse.ArgumentParser(description="Push an imported dataset to GitHub and optionally create a PR.")
    parser.add_argument("--record", required=True, help="Zenodo Record ID")
    parser.add_argument("--basedir", default=".", help="Base directory for the projects")
    parser.add_argument("--org", default="conp-bot", help="GitHub organization/user")
    parser.add_argument("--pr", action="store_true", help="Create a Pull Request to CONP-PCNO/conp-dataset")
    parser.add_argument("--main-repo", help="Path to the main conp-dataset repository")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without doing it")
    args = parser.parse_args()

    record_id = args.record.split("/")[-1]
    
    print(f"🔍 Searching for dataset with record ID: {record_id}...")
    dataset_dir = find_dataset_dir(args.basedir, record_id)
    
    if not dataset_dir:
        print(f"❌ Error: Could not find dataset directory for record {record_id} in {args.basedir}/projects")
        return

    folder_name = os.path.basename(dataset_dir)
    repo_name = get_repo_name(folder_name)
    repo_url = f"https://github.com/{args.org}/{repo_name}.git"
    
    print(f"📂 Found dataset at: {dataset_dir}")
    print(f"🏷️  Suggested repo name: {repo_name}")
    print(f"🔗 Target URL: {repo_url}")

    if args.dry_run and not args.pr:
        print("\n--- DRY RUN ---")
        print(f"Would check if repo exists: gh repo view {args.org}/{repo_name}")
        print(f"Would create repo if missing: gh repo create {args.org}/{repo_name} --public")
        print(f"Would update git remote origin to: {repo_url}")
        print(f"Would push branches: main, git-annex")
    
    if not args.dry_run:
        # 1. Check if repo exists
        print(f"📡 Checking if repository {args.org}/{repo_name} exists...")
        try:
            run(["gh", "repo", "view", f"{args.org}/{repo_name}"], capture_output=True)
            print("✅ Repository already exists.")
        except subprocess.CalledProcessError:
            print(f"➕ Creating new repository: {args.org}/{repo_name}...")
            run(["gh", "repo", "create", f"{args.org}/{repo_name}", "--public", "--confirm"])

        # 2. Update remote
        print("🔄 Updating git remotes...")
        try:
            run(["git", "remote", "remove", "origin"], cwd=dataset_dir)
        except subprocess.CalledProcessError:
            pass # origin might not exist
        
        run(["git", "remote", "add", "origin", repo_url], cwd=dataset_dir)

        # 3. Push branches
        print("🚀 Detecting branch name...")
        branch_result = run(["git", "symbolic-ref", "--short", "HEAD"], cwd=dataset_dir, capture_output=True)
        current_branch = branch_result.stdout.strip()
        print(f"🚀 Pushing {current_branch} branch...")
        run(["git", "push", "-u", "--force", "origin", current_branch], cwd=dataset_dir)
        
        print("🚀 Pushing git-annex branch...")
        try:
            run(["git", "push", "--force", "origin", "git-annex"], cwd=dataset_dir)
        except subprocess.CalledProcessError:
            print("⚠️  Warning: git-annex branch push failed (it might not exist if no large files were added).")

    # 4. Handle PR workflow
    if args.pr:
        main_repo_path = args.main_repo or os.path.abspath(args.basedir)
        create_pull_request(main_repo_path, dataset_dir, repo_url, repo_name, args.org, record_id, args.dry_run)

    print(f"\n✨ Success! Workflow complete.")

if __name__ == "__main__":
    main()
