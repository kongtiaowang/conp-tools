#!/usr/bin/env python3
"""
run_pipeline.py — CONP 全流程批量编排脚本
check → import → push，每次只推一个数据集，支持断点续传

用法:
    python run_pipeline.py                         # 全流程（检查 + import + push）
    python run_pipeline.py --dry-run               # 演练，不实际执行
    python run_pipeline.py --skip-check            # 跳过 check，使用上次报告
    python run_pipeline.py --id abc12 --type osf   # 手动单个
    python run_pipeline.py --retry-failed          # 重试失败的
    python run_pipeline.py --reset-state           # 清空进度重来
    python run_pipeline.py --status                # 查看当前进度
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

# ── 配置 ─────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "conp-dataset_path": "/data/crawler/push_new_repo/conp-dataset-main",
    "scripts_dir": os.path.dirname(os.path.abspath(__file__)),
    "org": "conp-bot",
}

STATE_FILE = os.path.expanduser("~/.conp_pipeline_state.json")
INTER_DATASET_DELAY = 10  # 推送间隔秒数，保护 GitHub rate limit

# ── 工具函数 ──────────────────────────────────────────────────────────────────

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


def run_subprocess(cmd: list, dry_run: bool = False) -> bool:
    log(f"CMD: {' '.join(cmd)}", "run")
    if dry_run:
        log("[DRY RUN] 跳过实际执行", "warn")
        return True
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        log(f"命令失败 (exit {result.returncode})", "err")
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


# ── 进度显示 ──────────────────────────────────────────────────────────────────

def print_progress(current: int, total: int, succeeded: int, failed: int, skipped: int, title: str):
    bar_len = 40
    filled = int(bar_len * current / total) if total else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    pct = int(100 * current / total) if total else 0
    print(f"\n  [{bar}] {pct}% ({current}/{total})")
    print(f"  ✅ {succeeded}  ❌ {failed}  ⏭️  {skipped}  当前: {title[:45]}\n", flush=True)


def print_status(state: dict):
    print(f"\n{'═' * 60}")
    print(f"  PIPELINE STATE  ({STATE_FILE})")
    print(f"{'═' * 60}")
    print(f"  ✅ 已成功: {len(state['processed'])}")
    print(f"  ❌ 已失败: {len(state['failed'])}")
    if state["processed"]:
        print("\n  成功列表:")
        for k, v in state["processed"].items():
            print(f"    {k}  [{v.get('time','?')[:16]}]  {v.get('title','')[:40]}")
    if state["failed"]:
        print("\n  失败列表:")
        for k, v in state["failed"].items():
            print(f"    {k}  step={v.get('step','?')}  {v.get('title','')[:40]}")
    print(f"{'═' * 60}\n")


# ── Step 1: Check ─────────────────────────────────────────────────────────────

def check_new_datasets(scripts_dir: str, conp_path: str, run_updates: bool = True) -> list:
    datasets = []
    
    # 1. 检查新发现的数据集
    log("Step 1/3 — 检查新数据集 (check_new_datasets.py)...", "run")
    check_script = os.path.join(scripts_dir, "check_new_datasets.py")
    subprocess.run([sys.executable, check_script], text=True)
    datasets.extend(_load_latest_report(conp_path, "dataset_discovery_"))
    
    # 2. 检查已有数据集的更新
    if run_updates:
        log("检查已有数据集的更新 (check_updates.py)...", "run")
        update_script = os.path.join(scripts_dir, "check_updates.py")
        subprocess.run([sys.executable, update_script], text=True)
        update_list = _load_latest_report(conp_path, "dataset_updates_")
        # 标记这些为更新任务，以便 pipeline 强制执行
        for d in update_list:
            d["is_update"] = True
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
        log("没有找到报告文件", "warn")
        return []
    latest = os.path.join(log_dir, files[0])
    log(f"读取报告: {os.path.basename(latest)}")
    with open(latest) as f:
        report = json.load(f)
    datasets = report.get("new_datasets", [])
    log(f"发现 {len(datasets)} 个新数据集", "ok")
    return datasets


# ── Step 2: Import ────────────────────────────────────────────────────────────

def import_one(dataset: dict, scripts_dir: str, conp_path: str, dry_run: bool) -> bool:
    source = dataset.get("source", "?")
    uid = dataset_uid(dataset)

    if source == "zenodo":
        script = os.path.join(scripts_dir, "import_single_zenodo_to_local_datalad.py")
        if not os.path.exists(script):
            log(f"Import 脚本不存在: {script}", "err")
            return False
        cmd = [sys.executable, script, "--record", uid, "--basedir", conp_path]

    elif source == "osf":
        script = os.path.join(scripts_dir, "import_single_osf_to_local_datalad.py")
        if not os.path.exists(script):
            log(f"Import 脚本不存在: {script}", "err")
            return False
        cmd = [sys.executable, script, "--node", uid, "--basedir", conp_path]
        token = os.environ.get("OSF_TOKEN")
        if token:
            cmd += ["--osf-token", token]
    else:
        log(f"未知来源: {source}", "err")
        return False

    return run_subprocess(cmd, dry_run)


# ── Step 3: Push + PR ─────────────────────────────────────────────────────────

def push_one(dataset: dict, scripts_dir: str, conp_path: str, org: str, dry_run: bool) -> bool:
    uid = dataset_uid(dataset)
    push_script = os.path.join(scripts_dir, "push_to_github.py")

    # 每次只推一个 ID，push_to_github.py 的 --record 保证单一子模块
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

    return run_subprocess(cmd, dry_run=False)  # dry_run flag 已通过参数传入脚本


# ── 单个数据集全流程 ───────────────────────────────────────────────────────────

def process_one(dataset: dict, scripts_dir: str, conp_path: str,
                org: str, dry_run: bool, state: dict) -> str:
    """返回: 'ok' | 'skip' | 'fail_import' | 'fail_push'"""
    key = dataset_key(dataset)
    title = dataset.get("title", "?")

    is_update = dataset.get("is_update", False)

    if key in state["processed"] and not is_update:
        log(f"已处理过且无更新，跳过: {key}", "skip")
        return "skip"
    
    if is_update:
        log(f"检测到更新，强制执行: {key}", "warn")

    print(f"\n  {'─' * 58}")
    log(f"处理: {key}")
    log(f"标题: {title}")
    print(f"  {'─' * 58}")

    log("Step 2/3 — Import...", "run")
    if not import_one(dataset, scripts_dir, conp_path, dry_run):
        state["failed"][key] = {
            "step": "import", "title": title, "time": datetime.now().isoformat()
        }
        save_state(state)
        return "fail_import"

    log("Step 3/3 — Push + PR（仅本 ID）...", "run")
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
    log(f"完成: {key}", "ok")
    return "ok"


# ── 批量执行 ──────────────────────────────────────────────────────────────────

def run_batch(datasets: list, scripts_dir: str, conp_path: str,
              org: str, dry_run: bool, state: dict, delay: int) -> bool:
    total = len(datasets)
    succeeded = failed = skipped = 0
    start = time.time()

    print(f"\n{'═' * 60}")
    print(f"  批量处理: {total} 个数据集（串行，每次一个 ID）")
    print(f"  推送间隔: {delay}s   dry-run: {dry_run}")
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
            log(f"等待 {delay}s（GitHub rate limit 保护）...", "warn")
            time.sleep(delay)

    elapsed = int(time.time() - start)
    mins, secs = divmod(elapsed, 60)

    print(f"\n{'═' * 60}")
    print(f"  批量完成  用时: {mins}m {secs}s")
    print(f"  ✅ 成功: {succeeded}  ❌ 失败: {failed}  ⏭️  跳过: {skipped}")
    if failed:
        print(f"\n  失败数据集:")
        for k, v in state["failed"].items():
            print(f"    {k}  step={v.get('step')}  {v.get('title','')[:40]}")
        print(f"\n  重试: python {os.path.basename(__file__)} --retry-failed")
    print(f"{'═' * 60}\n")

    return failed == 0


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CONP 批量 check → import → push 流水线")
    parser.add_argument("--dry-run", action="store_true", help="演练模式，不实际执行")
    parser.add_argument("--skip-check", action="store_true", help="跳过 check，使用最新报告")
    parser.add_argument("--id", metavar="ID", help="手动指定单个 record/node ID")
    parser.add_argument("--type", choices=["zenodo", "osf"], help="配合 --id 使用")
    parser.add_argument("--retry-failed", action="store_true", help="重试失败的数据集")
    parser.add_argument("--reset-state", action="store_true", help="清空进度，从头开始")
    parser.add_argument("--status", action="store_true", help="查看当前进度")
    parser.add_argument("--org", metavar="ORG", help="GitHub 组织/用户名")
    parser.add_argument("--delay", type=int, default=INTER_DATASET_DELAY,
                        help=f"数据集间等待秒数（默认 {INTER_DATASET_DELAY}）")
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
        log("进度状态已清空", "ok")
        return

    print(f"\n{'═' * 60}")
    print(f"  CONP PIPELINE  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  conp-dataset : {conp_path}")
    print(f"  org          : {org}")
    print(f"  dry-run      : {args.dry_run}")
    print(f"  state file   : {STATE_FILE}")
    print(f"{'═' * 60}")

    # ── 手动单个 ──────────────────────────────────────────────
    if args.id:
        if not args.type:
            log("--type (zenodo 或 osf) 与 --id 必须同时指定", "err")
            sys.exit(1)
        if args.type == "zenodo":
            dataset = {"source": "zenodo", "record_id": args.id,
                       "identifiers": [args.id], "title": f"manual:{args.id}"}
        else:
            dataset = {"source": "osf", "osf_id": args.id,
                       "identifiers": [args.id], "title": f"manual:{args.id}"}
        result = process_one(dataset, scripts_dir, conp_path, org, args.dry_run, state)
        sys.exit(0 if result in ("ok", "skip") else 1)

    # ── 重试失败 ───────────────────────────────────────────────
    if args.retry_failed:
        if not state["failed"]:
            log("没有失败记录", "ok")
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

    # ── 正常批量流程 ───────────────────────────────────────────
    if args.skip_check:
        log("加载最新报告...")
        datasets = _load_latest_report(conp_path)
    else:
        datasets = check_new_datasets(scripts_dir, conp_path)

    if not datasets:
        log("没有新数据集，结束", "ok")
        return

    # 断点续传：过滤已成功的
    remaining = [d for d in datasets if dataset_key(d) not in state["processed"]]
    done_count = len(datasets) - len(remaining)
    if done_count:
        log(f"断点续传：跳过 {done_count} 个已完成，剩余 {len(remaining)} 个", "skip")

    if not remaining:
        log("所有数据集均已处理", "ok")
        return

    ok = run_batch(remaining, scripts_dir, conp_path, org, args.dry_run, state, args.delay)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()