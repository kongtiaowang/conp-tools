#!/usr/bin/env python3
"""
run_pipeline.py — CONP end-to-end batch orchestrator
check -> import -> push, one dataset per push, resumable

Usage:
    python run_pipeline.py                         # full pipeline (check + import + push)
    python run_pipeline.py --dry-run               # dry run, execute nothing
    python run_pipeline.py --skip-check            # skip check and reuse the last report
    python run_pipeline.py --id abc12 --type osf   # handle a single dataset manually
    python run_pipeline.py --retry-failed          # retry the failed ones
    python run_pipeline.py --reset-state           # wipe progress and start over
    python run_pipeline.py --status                # show current progress
"""

import argparse
import json
import os
import subprocess
import sys
import re
import time
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "conp-dataset_path": "/data/crawler/push_new_repo/conp-dataset-main",
    "scripts_dir": os.path.dirname(os.path.abspath(__file__)),
    "org": "conp-bot",
}

STATE_FILE = os.path.expanduser("~/.conp_pipeline_state.json")
INTER_DATASET_DELAY = 10  # Seconds between pushes, to stay under GitHub rate limits

# ── Helper functions ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = os.path.expanduser("~/.conp_crawler_config.json")
    if os.path.exists(path):
        with open(path) as f:
            cfg.update(json.load(f))
    return cfg


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"processed": {}, "failed": {}}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def log(msg: str, level: str = "info"):
    icons = {"info": "  ", "ok": "✅", "warn": "⚠️ ", "err": "❌", "skip": "⏭️ ", "run": "🚀"}
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {icons.get(level,'  ')} {msg}", flush=True)


def clean_title(title: str) -> str:
    """Safe title for folder/repo names."""
    clean = re.sub(r'[<>:"/\\|?*]', '_', title)
    clean = re.sub(r'\s+', '_', clean)
    clean = re.sub(r'_+', '_', clean)
    clean = clean.strip('_')
    return clean

def clean_title(title: str) -> str:
    """Safe title for folder/repo names."""
    clean = re.sub(r'[<>:"/\\|?*]', '_', title)
    clean = re.sub(r'\s+', '_', clean)
    clean = re.sub(r'_+', '_', clean)
    clean = clean.strip('_')
    return clean

def run_subprocess(cmd: list[str], dry_run: bool = False, cwd: str | None = None) -> bool:
    """Run a subprocess and report whether it succeeded"""
    if dry_run:
        log(f"[DRY-RUN] would run: {' '.join(cmd)}", "warn")
        return True
    
    try:
        subprocess.run(cmd, check=True, text=True, cwd=cwd)
        return True
    except subprocess.CalledProcessError as e:
        log(f"Command failed: {' '.join(cmd)} (exit {e.returncode})", "err")
        return False
    return True


def dataset_key(dataset: dict) -> str:
    source = dataset.get("source", "?")
    uid = (dataset.get("record_id")
           or dataset.get("osf_id")
           or (dataset.get("identifiers") or ["?"])[0])
    return f"{source}:{uid}"


def dataset_uid(dataset: dict) -> str:
    return (dataset.get("record_id")
            or dataset.get("osf_id")
            or (dataset.get("identifiers") or ["?"])[0])


# ── Progress ──────────────────────────────────────────────────────────────────

def print_progress(current: int, total: int, succeeded: int, failed: int, skipped: int, title: str):
    bar_len = 40
    filled = int(bar_len * current / total) if total else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    pct = int(100 * current / total) if total else 0
    print(f"\n  [{bar}] {pct}% ({current}/{total})")
    print(f"  ✅ {succeeded}  ❌ {failed}  ⏭️  {skipped}  current: {title[:45]}\n", flush=True)


def print_status(state: dict):
    print(f"\n{'═' * 60}")
    print(f"  PIPELINE STATE  ({STATE_FILE})")
    print(f"{'═' * 60}")
    print(f"  ✅ Succeeded: {len(state['processed'])}")
    print(f"  ❌ Failed: {len(state['failed'])}")
    if state["processed"]:
        print("\n  Succeeded:")
        for k, v in state["processed"].items():
            print(f"    {k}  [{v.get('time','?')[:16]}]  {v.get('title','')[:40]}")
    if state["failed"]:
        print("\n  Failed:")
        for k, v in state["failed"].items():
            print(f"    {k}  step={v.get('step','?')}  {v.get('title','')[:40]}")
    print(f"{'═' * 60}\n")


# ── Step 1: Check ─────────────────────────────────────────────────────────────

def check_new_datasets(scripts_dir: str, conp_path: str, run_updates: bool = True) -> list:
    datasets = []
    
    # 1. Check for newly discovered datasets
    log("Step 1/3 — checking for new datasets (check_new_datasets.py)...", "run")
    check_script = os.path.join(scripts_dir, "check_new_datasets.py")
    subprocess.run([sys.executable, check_script], text=True)
    datasets.extend(_load_latest_report(conp_path, "dataset_discovery_"))
    
    # 2. Check for updates to existing datasets
    if run_updates:
        log("checking for updates to existing datasets (check_updates.py)...", "run")
        # Ensure the submodule is initialized and up to date if it's an update
        # This is CRITICAL so the import script can read the existing DATS.json for merging
        # Note: folder_name logic should be derived from specific dataset objects
        
        update_script = os.path.join(scripts_dir, "check_updates.py")
        subprocess.run([sys.executable, update_script], text=True)
        update_list = _load_latest_report(conp_path, "dataset_updates_")
        # Mark these as update tasks so the pipeline forces them through
        for d in update_list:
            d["is_update"] = True
            
            # Initialize submodule for the update
            folder_name = d.get("folder_name")
            if folder_name:
                print(f"🔄 Initializing existing submodule to preserve metadata: {folder_name}...")
                try:
                    run_subprocess(["git", "submodule", "update", "--init", f"projects/{folder_name}"], cwd=conp_path)
                except:
                    print(f"⚠️  Could not initialize submodule projects/{folder_name}. Metadata merge might fallback to template.")
        
        datasets.extend(update_list)
        
    return datasets


def _load_latest_report(conp_path: str, prefix: str) -> list:
    log_dir = os.path.join(conp_path, "log")
    if not os.path.isdir(log_dir):
        return []
    files = sorted(
        [f for f in os.listdir(log_dir)
         if f.startswith(prefix) and f.endswith(".json")],
        reverse=True,
    )
    if not files:
        log("No report file found", "warn")
        return []
    latest = os.path.join(log_dir, files[0])
    log(f"Reading report: {os.path.basename(latest)}")
    with open(latest) as f:
        report = json.load(f)
    datasets = report.get("new_datasets", [])
    log(f"Found {len(datasets)} new datasets", "ok")
    return datasets


# ── Step 2: Import ────────────────────────────────────────────────────────────

def import_one(dataset: dict, scripts_dir: str, conp_path: str, dry_run: bool) -> bool:
    source = dataset.get("source", "?")
    uid = dataset_uid(dataset)

    if source == "zenodo":
        script = os.path.join(scripts_dir, "import_single_zenodo_to_local_datalad.py")
        if not os.path.exists(script):
            log(f"Import script not found: {script}", "err")
            return False
        cmd = [sys.executable, script, "--record", uid, "--basedir", conp_path]

    elif source == "osf":
        script = os.path.join(scripts_dir, "import_single_osf_to_local_datalad.py")
        if not os.path.exists(script):
            log(f"Import script not found: {script}", "err")
            return False
        cmd = [sys.executable, script, "--node", uid, "--basedir", conp_path]
        token = os.environ.get("OSF_TOKEN")
        if token:
            cmd += ["--osf-token", token]
    else:
        log(f"Unknown source: {source}", "err")
        return False

    return run_subprocess(cmd, dry_run)


# ── Step 3: Push + PR ─────────────────────────────────────────────────────────

def push_one(dataset: dict, scripts_dir: str, conp_path: str, org: str, dry_run: bool) -> bool:
    uid = dataset_uid(dataset)
    push_script = os.path.join(scripts_dir, "push_to_github.py")

    # One ID per push; --record in push_to_github.py keeps it to a single submodule
    cmd = [
        sys.executable, push_script,
        "--record", uid,
        "--basedir", conp_path,
        "--org", org,
        "--main-repo", conp_path,
        "--pr",
    ]
    if dry_run:
        cmd.append("--dry-run")
    if dataset.get("is_update"):
        cmd.append("--update")

    return run_subprocess(cmd, dry_run=False)  # the dry_run flag is forwarded to the script via arguments


# ── Per-dataset pipeline ───────────────────────────────────────────────────────────

def process_one(dataset: dict, scripts_dir: str, conp_path: str,
                org: str, dry_run: bool, state: dict) -> str:
    """Returns: 'ok' | 'skip' | 'fail_import' | 'fail_push'"""
    key = dataset_key(dataset)
    title = dataset.get("title", "?")

    is_update = dataset.get("is_update", False)

    if key in state["processed"] and not is_update:
        log(f"Already processed and unchanged, skipping: {key}", "skip")
        return "skip"
    
    if is_update:
        log(f"Update detected, forcing: {key}", "warn")

    print(f"\n  {'─' * 58}")
    log(f"Processing: {key}")
    log(f"Title: {title}")
    print(f"  {'─' * 58}")

    log("Step 2/3 — Import...", "run")
    
    # 🚨 CRITICAL: For updates, we MUST ensure the existing submodule is checked out
    if is_update:
        # Find the actual folder name by scanning the main repo's projects
        target_id = dataset.get("record_id") or dataset.get("osf_id")
        found_folder = None
        
        # Look into the project directories in the main repo
        projects_dir = os.path.join(conp_path, "projects")
        if os.path.exists(projects_dir):
            for folder in os.listdir(projects_dir):
                dats_file = os.path.join(projects_dir, folder, "DATS.json")
                if os.path.exists(dats_file):
                    try:
                        with open(dats_file, "r") as f:
                            dats = json.load(f)
                        # Check extraProperties for the ID
                        for prop in dats.get("extraProperties", []):
                            if prop.get("category") in ["osf_node_id", "zenodo_record_id"]:
                                if any(v.get("value") == target_id for v in prop.get("values", [])):
                                    found_folder = folder
                                    break
                        if found_folder: break
                    except: pass
        
        if found_folder:
            print(f"🔄 Initializing existing submodule: projects/{found_folder} (matches ID {target_id})...")
            try:
                run_subprocess(["git", "submodule", "update", "--init", f"projects/{found_folder}"], dry_run=False, cwd=conp_path)
            except:
                print(f"⚠️  Could not initialize submodule projects/{found_folder}.")
        else:
            print(f"ℹ️  Could not find an existing submodule for ID {target_id}, might be a new dataset.")

    if not import_one(dataset, scripts_dir, conp_path, dry_run):
        state["failed"][key] = {
            "step": "import", "title": title, "time": datetime.now().isoformat()
        }
        save_state(state)
        return "fail_import"

    log("Step 3/3 — push + PR (this ID only)...", "run")
    if not push_one(dataset, scripts_dir, conp_path, org, dry_run):
        state["failed"][key] = {
            "step": "push", "title": title, "time": datetime.now().isoformat()
        }
        save_state(state)
        return "fail_push"

    state["processed"][key] = {"title": title, "time": datetime.now().isoformat()}
    if key in state["failed"]:
        del state["failed"][key]
    save_state(state)
    log(f"Done: {key}", "ok")
    return "ok"


# ── Batch run ──────────────────────────────────────────────────────────────────

def run_batch(datasets: list, scripts_dir: str, conp_path: str,
              org: str, dry_run: bool, state: dict, delay: int) -> bool:
    total = len(datasets)
    succeeded = failed = skipped = 0
    start = time.time()

    print(f"\n{'═' * 60}")
    print(f"  Batch: {total} datasets (serial, one ID at a time)")
    print(f"  Push interval: {delay}s   dry-run: {dry_run}")
    print(f"{'═' * 60}")

    for i, dataset in enumerate(datasets):
        title = dataset.get("title", "?")
        print_progress(i, total, succeeded, failed, skipped, title)

        result = process_one(dataset, scripts_dir, conp_path, org, dry_run, state)

        if result == "ok":
            succeeded += 1
        elif result == "skip":
            skipped += 1
        else:
            failed += 1

        if i < total - 1 and result != "skip":
            log(f"Waiting {delay}s (GitHub rate-limit guard)...", "warn")
            time.sleep(delay)

    elapsed = int(time.time() - start)
    mins, secs = divmod(elapsed, 60)

    print(f"\n{'═' * 60}")
    print(f"  Batch complete, elapsed: {mins}m {secs}s")
    print(f"  ✅ Succeeded: {succeeded}  ❌ Failed: {failed}  ⏭️  Skipped: {skipped}")
    if failed:
        print(f"\n  Failed datasets:")
        for k, v in state["failed"].items():
            print(f"    {k}  step={v.get('step')}  {v.get('title','')[:40]}")
        print(f"\n  Retry: python {os.path.basename(__file__)} --retry-failed")
    print(f"{'═' * 60}\n")

    return failed == 0


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CONP batch check -> import -> push pipeline")
    parser.add_argument("--dry-run", action="store_true", help="dry run; do not execute anything")
    parser.add_argument("--skip-check", action="store_true", help="skip check and use the latest report")
    parser.add_argument("--id", metavar="ID", help="manually specify a single record/node ID")
    parser.add_argument("--type", choices=["zenodo", "osf"], help="used together with --id")
    parser.add_argument("--retry-failed", action="store_true", help="retry the failed datasets")
    parser.add_argument("--reset-state", action="store_true", help="clear progress and start over")
    parser.add_argument("--status", action="store_true", help="show current progress")
    parser.add_argument("--org", metavar="ORG", help="GitHub org/username")
    parser.add_argument("--delay", type=int, default=INTER_DATASET_DELAY,
                        help=f"seconds to wait between datasets (default {INTER_DATASET_DELAY})")
    args = parser.parse_args()

    cfg = load_config()
    scripts_dir = cfg.get("scripts_dir", os.path.dirname(os.path.abspath(__file__)))
    conp_path = cfg.get("conp-dataset_path", "/data/crawler/conp-dataset")
    org = args.org or cfg.get("org", "conp-bot")
    state = load_state()

    if args.status:
        print_status(state)
        return

    if args.reset_state:
        save_state({"processed": {}, "failed": {}})
        log("Progress state cleared", "ok")
        return

    print(f"\n{'═' * 60}")
    print(f"  CONP PIPELINE  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  conp-dataset : {conp_path}")
    print(f"  org          : {org}")
    print(f"  dry-run      : {args.dry_run}")
    print(f"  state file   : {STATE_FILE}")
    print(f"{'═' * 60}")

    # ── Manual single ──────────────────────────────────────────────
    if args.id:
        if not args.type:
            log("--type (zenodo or osf) and --id must be given together", "err")
            sys.exit(1)
        if args.type == "zenodo":
            dataset = {"source": "zenodo", "record_id": args.id,
                       "identifiers": [args.id], "title": f"manual:{args.id}",
                       "is_update": True}
        else:
            dataset = {"source": "osf", "osf_id": args.id,
                       "identifiers": [args.id], "title": f"manual:{args.id}",
                       "is_update": True}
        result = process_one(dataset, scripts_dir, conp_path, org, args.dry_run, state)
        sys.exit(0 if result in ("ok", "skip") else 1)

    # ── Retry failed ───────────────────────────────────────────────
    if args.retry_failed:
        if not state["failed"]:
            log("No failed records", "ok")
            return
        datasets = []
        for key, info in list(state["failed"].items()):
            source, uid = key.split(":", 1)
            if source == "zenodo":
                datasets.append({"source": "zenodo", "record_id": uid,
                                  "identifiers": [uid], "title": info["title"]})
            else:
                datasets.append({"source": "osf", "osf_id": uid,
                                  "identifiers": [uid], "title": info["title"]})
            del state["failed"][key]
            if key in state["processed"]:
                del state["processed"][key]
        save_state(state)
        ok = run_batch(datasets, scripts_dir, conp_path, org, args.dry_run, state, args.delay)
        sys.exit(0 if ok else 1)

    # ── Normal batch flow ───────────────────────────────────────────
    if args.skip_check:
        log("Loading the latest report...")
        datasets = _load_latest_report(conp_path)
    else:
        datasets = check_new_datasets(scripts_dir, conp_path)

    if not datasets:
        log("No new datasets, done", "ok")
        return

    # Resume support: filter out the already-succeeded ones
    remaining = [d for d in datasets if dataset_key(d) not in state["processed"]]
    done_count = len(datasets) - len(remaining)
    if done_count:
        log(f"Resuming: skipping {done_count} already done, {len(remaining)} remaining", "skip")

    if not remaining:
        log("All datasets have been processed", "ok")
        return

    ok = run_batch(remaining, scripts_dir, conp_path, org, args.dry_run, state, args.delay)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()