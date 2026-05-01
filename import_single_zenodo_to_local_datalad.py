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


ZENODO_PROVIDER_CONFIG = """[provider:ZENODO]
url_re = .*zenodo\\.org.*
authentication_type = bearer_token
credential = ZENODO

[credential:ZENODO]
# If known, specify URL or email to how/where to request credentials
# url = ???
type = token
"""


def run(cmd: list[str], cwd: str | None = None):
    subprocess.run(cmd, cwd=cwd, check=True)


def capture(cmd: list[str], cwd: str | None = None) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True)


def clean_title(title: str) -> str:
    return re.sub(r"\W|^(?=\d)", "_", title)


def html_to_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
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


def load_zenodo_token(config_path: str | None, arg_token: str | None) -> str | None:
    if arg_token:
        return arg_token
    env_token = os.getenv("ZENODO_TOKEN") or os.getenv("DATALAD_ZENODO_token")
    if env_token:
        return env_token
    if config_path and os.path.isfile(config_path):
        with open(config_path) as f:
            data = json.load(f)
        return data.get("zenodo_token")
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


def ensure_dataset_dir(dataset_dir: str):
    os.makedirs(dataset_dir, exist_ok=True)
    git_dir = os.path.join(dataset_dir, ".git")
    datalad_dir = os.path.join(dataset_dir, ".datalad")
    if not (os.path.isdir(git_dir) and os.path.isdir(datalad_dir)):
        parent_dir = os.path.dirname(dataset_dir)
        run(["datalad", "create","-f", os.path.basename(dataset_dir)], cwd=parent_dir)


def ensure_zenodo_provider(dataset_dir: str, token: str | None):
    if not token:
        return
    datalad_dir = os.path.join(dataset_dir, ".datalad")
    providers_dir = os.path.join(datalad_dir, "providers")
    os.makedirs(providers_dir, exist_ok=True)
    config_path = os.path.join(providers_dir, "ZENODO.cfg")
    with open(config_path, "w") as f:
        f.write(ZENODO_PROVIDER_CONFIG)
    run(["datalad", "no-annex", "--pattern", "**/ZENODO.cfg"], cwd=dataset_dir)
    os.environ["DATALAD_ZENODO_token"] = token


def get_download_url(file_item: dict) -> str:
    return file_item["links"]["self"]


def download_files(
    files: list[dict],
    dataset_dir: str,
    file_sizes: list[int],
):
    for file_item in files:
        name = file_item.get("key")
        if not name:
            continue

        target_rel = name
        target_abs = os.path.join(dataset_dir, target_rel)
        os.makedirs(os.path.dirname(target_abs) or dataset_dir, exist_ok=True)
        if os.path.lexists(target_abs):
            continue
        run(
            ["datalad", "download-url", "--path", target_rel, get_download_url(file_item)],
            cwd=dataset_dir,
        )
        file_size = file_item.get("size")
        if file_size:
            file_sizes.append(int(file_size))


def build_description(record: dict) -> dict:
    metadata = record.get("metadata", {})
    keywords = [{"value": value} for value in metadata.get("keywords", [])]
    creators = [{"name": creator.get("name")} for creator in metadata.get("creators", [])]
    
    license_name = metadata.get("license", {}).get("id", "None")
    
    description = metadata.get("description", "")

    extra_properties = [
        {
            "category": "logo",
            "values": [
                {
                    "value": "https://about.zenodo.org/static/img/logos/zenodo-gradient-round.svg"
                }
            ],
        }
    ]

    is_about = []
    if "subjects" in metadata:
        for subject in metadata["subjects"]:
            if "identifier" in subject and "term" in subject:
                if re.match(r".*ncbi\.nlm\.nih\.gov/taxonomy.*", subject["identifier"]):
                    is_about.append(
                        {
                            "identifier": {"identifier": subject["identifier"]},
                            "name": subject["term"],
                        }
                    )
                else:
                    is_about.append(
                        {
                            "valueIRI": subject["identifier"],
                            "value": subject["term"],
                        }
                    )
    
    def format_date(d_str):
        if not d_str:
            return ""
        return d_str.split(".")[0].replace("T", " ")

    date_created_str = record.get("created", "")
    date_modified_str = record.get("updated", "")
    homepage = record.get("links", {}).get("self_html", f"https://zenodo.org/records/{record.get('id')}")
    
    dataset = {
        "record_id": record.get("id"),
        "concept_doi": record.get("conceptrecid"),
        "title": metadata.get("title", ""),
        "homepage": homepage,
        "creators": creators,
        "description": description,
        "version": metadata.get("version", "None"),
        "licenses": [{"name": license_name}],
        "dates": [
            {
                "date": format_date(date_created_str),
                "type": {"value": "date created"},
            },
            {
                "date": format_date(date_modified_str),
                "type": {"value": "date modified"},
            },
        ],
        "keywords": keywords,
        "distributions": [
            {
                "size": 0,
                "unit": {"value": "B"},
                "access": {
                    "landingPage": homepage,
                    "authorizations": [
                        {
                            "value": "public" if metadata.get("access_right") == "open" else "private",
                        }
                    ],
                },
            }
        ],
        "extraProperties": extra_properties,
        "isAbout": is_about,
    }

    identifier = record.get("doi") or metadata.get("doi")
    if identifier:
        dataset["identifier"] = {
            "identifier": f"https://doi.org/{identifier}" if not identifier.startswith("http") else identifier,
            "identifierSource": "DOI",
        }

    return dataset


def create_tracker(path: str, dataset: dict):
    with open(path, "w") as f:
        json.dump(
            {
                "zenodo": {
                    "concept_doi": dataset["concept_doi"],
                    "version": dataset["version"],
                },
                "title": dataset["title"],
            },
            f,
            indent=4,
        )


def write_readme(path: str, dataset: dict):
    content = f'# {dataset["title"]}\n\nCrawled from [Zenodo]({dataset["homepage"]})'
    if dataset.get("description"):
        content += f'\n\n## Description\n\n{html_to_text(dataset["description"])}'
    if dataset.get("identifier"):
        content += f'\n\n## DOI\n\n{dataset["identifier"]["identifier"]}'
    with open(path, "w") as f:
        f.write(content)


def write_dats(path: str, dataset: dict, dataset_dir: str):
    dats_fields = {
        "identifier",
        "title",
        "description",
        "creators",
        "types",
        "version",
        "licenses",
        "keywords",
        "distributions",
        "extraProperties",
        "dates",
        "isAbout",
    }
    data = {key: value for key, value in dataset.items() if key in dats_fields}

    annex_list = capture(["git", "annex", "list"], cwd=dataset_dir).splitlines()
    file_paths = [line.split(" ")[-1] for line in annex_list if " " in line]
    data.setdefault("extraProperties", []).append(
        {"category": "files", "values": [{"value": str(len(file_paths))}]}
    )
    data.setdefault("types", [{"information": {"value": "unknown"}}])

    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def main():
    parser = argparse.ArgumentParser(description="Import one Zenodo dataset into a local DataLad dataset.")
    parser.add_argument("--record", required=True, help="Zenodo record id (e.g. 8364172) or URL")
    parser.add_argument("--basedir", default=".", help="Base directory to create the dataset in (default: current directory)")
    parser.add_argument(
        "--config",
        default=os.path.expanduser("~/.conp_crawler_config.json"),
        help="Optional crawler config JSON used to read zenodo_token",
    )
    parser.add_argument(
        "--zenodo-token",
        help="Zenodo bearer token. Falls back to ZENODO_TOKEN, DATALAD_ZENODO_token, then config file",
    )
    args = parser.parse_args()

    record_id = args.record
    if "zenodo.org/records/" in record_id:
        record_id = record_id.split("zenodo.org/records/")[-1].split("/")[0]
    elif "zenodo.org/record/" in record_id:
        record_id = record_id.split("zenodo.org/record/")[-1].split("/")[0]

    token = load_zenodo_token(args.config, args.zenodo_token)

    record = fetch_json(f"https://zenodo.org/api/records/{record_id}", token)
    dataset = build_description(record)

    dataset_dir = os.path.abspath(os.path.join(args.basedir, "projects", clean_title(dataset["title"])))

    ensure_dataset_dir(dataset_dir)
    ensure_zenodo_provider(dataset_dir, token)

    file_sizes: list[int] = []
    
    files = record.get("files", [])
    if files:
        download_files(files, dataset_dir, file_sizes)

    dataset_size, dataset_unit = natural_size(sum(file_sizes))
    dataset["distributions"][0]["size"] = dataset_size
    dataset["distributions"][0]["unit"]["value"] = dataset_unit

    create_tracker(os.path.join(dataset_dir, ".conp-zenodo-crawler.json"), dataset)
    write_readme(os.path.join(dataset_dir, "README.md"), dataset)
    write_dats(os.path.join(dataset_dir, "DATS.json"), dataset, dataset_dir)
    
    run(["git", "add", ".conp-zenodo-crawler.json", "README.md", "DATS.json"], cwd=dataset_dir)
    run(["datalad", "save", "-m", f"Import Zenodo record {record_id}"], cwd=dataset_dir)

    print(clean_title(dataset["title"]))
    print(dataset["title"])


if __name__ == "__main__":
    main()

