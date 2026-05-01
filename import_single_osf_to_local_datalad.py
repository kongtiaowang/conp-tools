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


OSF_PROVIDER_CONFIG = """[provider:OSF]
url_re = .*osf\\.io.*
authentication_type = bearer_token
credential = OSF

[credential:OSF]
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


def normalize_node(node: str) -> str:
    node = node.strip().rstrip("/")
    if "/nodes/" in node:
        return node.split("/nodes/")[-1].split("/")[0]
    if "osf.io/" in node:
        return node.split("osf.io/")[-1].split("/")[0]
    return node


def load_osf_token(config_path: str | None, arg_token: str | None) -> str | None:
    if arg_token:
        return arg_token
    env_token = os.getenv("OSF_TOKEN") or os.getenv("DATALAD_OSF_token")
    if env_token:
        return env_token
    if config_path and os.path.isfile(config_path):
        with open(config_path) as f:
            data = json.load(f)
        return data.get("osf_token")
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


def fetch_paginated_data(url: str, token: str | None = None) -> list[dict]:
    items = []
    while url:
        payload = fetch_json(url, token=token)
        items.extend(payload.get("data", []))
        url = payload.get("links", {}).get("next")
    return items


def ensure_dataset_dir(dataset_dir: str):
    os.makedirs(dataset_dir, exist_ok=True)
    git_dir = os.path.join(dataset_dir, ".git")
    datalad_dir = os.path.join(dataset_dir, ".datalad")
    if not (os.path.isdir(git_dir) and os.path.isdir(datalad_dir)):
        parent_dir = os.path.dirname(dataset_dir)
        run(["datalad", "create", os.path.basename(dataset_dir)], cwd=parent_dir)


def ensure_osf_provider(dataset_dir: str, token: str | None):
    if not token:
        return
    datalad_dir = os.path.join(dataset_dir, ".datalad")
    providers_dir = os.path.join(datalad_dir, "providers")
    os.makedirs(providers_dir, exist_ok=True)
    config_path = os.path.join(providers_dir, "OSF.cfg")
    with open(config_path, "w") as f:
        f.write(OSF_PROVIDER_CONFIG)
    run(["datalad", "no-annex", "--pattern", "**/OSF.cfg"], cwd=dataset_dir)
    os.environ["DATALAD_OSF_token"] = token


def maybe_human_species(title: str, description: str) -> list[dict]:
    text = f"{title} {description}".lower()
    markers = [
        "participant",
        "participants",
        "adolescent",
        "adolescents",
        "children",
        "child",
        "adult",
        "adults",
        "pediatric",
        "human",
        "neurotypical",
    ]
    if any(marker in text for marker in markers):
        return [
            {
                "identifier": {
                    "identifier": "https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id=9606"
                },
                "name": "Homo sapiens",
            }
        ]
    return []


def get_contributors(link: str, token: str | None) -> list[str]:
    contributors = []
    for contributor in fetch_paginated_data(link, token):
        user = contributor.get("embeds", {}).get("users", {}).get("data", {})
        full_name = user.get("attributes", {}).get("full_name")
        if full_name:
            contributors.append(full_name)
    return contributors


def get_license(link: str, token: str | None) -> str:
    try:
        data = fetch_json(link, token)
        return data.get("data", {}).get("attributes", {}).get("name", "None")
    except urllib.error.HTTPError:
        return "None"


def get_institutions(link: str, token: str | None) -> list[str]:
    return [
        institution.get("attributes", {}).get("name")
        for institution in fetch_paginated_data(link, token)
        if institution.get("attributes", {}).get("name")
    ]


def get_identifier(link: str, token: str | None) -> str | None:
    for item in fetch_paginated_data(link, token):
        value = item.get("attributes", {}).get("value")
        if value:
            return value
    return None


def get_wiki(link: str, token: str | None) -> str | None:
    data = fetch_paginated_data(link, token)
    if not data:
        return None
    download_url = data[0].get("links", {}).get("download")
    if not download_url:
        return None
    with request(download_url, token=token) as response:
        return response.read().decode("utf-8")


def list_components(link: str, token: str | None) -> list[dict]:
    return fetch_paginated_data(link, token)


def is_private_files_link(files_url: str, token: str | None) -> bool:
    if token:
        try:
            fetch_json(files_url, token=token)
            return False
        except urllib.error.HTTPError as exc:
            return exc.code == 401
    try:
        fetch_json(files_url)
        return False
    except urllib.error.HTTPError as exc:
        return exc.code == 401


def get_download_url(file_item: dict) -> str:
    return file_item["links"]["download"]


def download_files(
    files_link: str,
    current_dir: str,
    inner_path: str,
    dataset_dir: str,
    token: str | None,
    file_sizes: list[int],
):
    for file_item in fetch_paginated_data(files_link, token):
        attributes = file_item.get("attributes", {})
        kind = attributes.get("kind")
        name = attributes.get("name")
        if not name:
            continue

        if kind == "folder":
            folder_current_dir = os.path.join(current_dir, name)
            folder_inner_path = os.path.join(inner_path, name)
            os.makedirs(folder_current_dir, exist_ok=True)
            download_files(
                file_item["relationships"]["files"]["links"]["related"]["href"],
                folder_current_dir,
                folder_inner_path,
                dataset_dir,
                token,
                file_sizes,
            )
            continue

        if kind != "file":
            continue

        target_rel = os.path.join(inner_path, name) if inner_path else name
        target_abs = os.path.join(dataset_dir, target_rel)
        os.makedirs(os.path.dirname(target_abs) or dataset_dir, exist_ok=True)
        if os.path.lexists(target_abs):
            continue
        run(
            ["datalad", "download-url", "--path", target_rel, get_download_url(file_item)],
            cwd=dataset_dir,
        )
        file_size = attributes.get("size")
        if file_size:
            file_sizes.append(int(file_size))


def download_components(
    components: list[dict],
    dataset_dir: str,
    token: str | None,
    file_sizes: list[int],
    inner_path: str = "",
):
    for component in components:
        component_title = clean_title(component.get("attributes", {}).get("title", "component"))
        component_inner_path = os.path.join(inner_path, "components", component_title)
        os.makedirs(os.path.join(dataset_dir, component_inner_path), exist_ok=True)
        download_files(
            component["relationships"]["files"]["links"]["related"]["href"],
            os.path.join(dataset_dir, component_inner_path),
            component_inner_path,
            dataset_dir,
            token,
            file_sizes,
        )
        subcomponents = list_components(
            component["relationships"]["children"]["links"]["related"]["href"],
            token,
        )
        if subcomponents:
            download_components(
                subcomponents,
                dataset_dir,
                token,
                file_sizes,
                component_inner_path,
            )


def build_description(node: dict, token: str | None) -> dict:
    attributes = node["attributes"]
    relationships = node["relationships"]
    keywords = [{"value": value} for value in attributes.get("tags", [])]
    contributors = get_contributors(
        relationships["contributors"]["links"]["related"]["href"],
        token,
    )
    license_name = "None"
    if "license" in relationships:
        license_name = get_license(
            relationships["license"]["links"]["related"]["href"],
            token,
        )
    institutions = get_institutions(
        relationships["affiliated_institutions"]["links"]["related"]["href"],
        token,
    )
    identifier = get_identifier(
        relationships["identifiers"]["links"]["related"]["href"],
        token,
    )
    files_link = relationships["files"]["links"]["related"]["href"]
    components = list_components(
        relationships["children"]["links"]["related"]["href"],
        token,
    )
    wiki = None
    try:
        wiki = get_wiki(relationships["wikis"]["links"]["related"]["href"], token)
    except urllib.error.HTTPError:
        wiki = None

    extra_properties = [
        {
            "category": "logo",
            "values": [
                {
                    "value": "https://osf.io/static/img/institutions/shields/cos-shield.png"
                }
            ],
        }
    ]
    if institutions:
        extra_properties.append(
            {
                "category": "origin_institution",
                "values": [{"value": item} for item in institutions],
            }
        )

    date_created = dt.datetime.strptime(attributes["date_created"], "%Y-%m-%dT%H:%M:%S.%f")
    date_modified = dt.datetime.strptime(attributes["date_modified"], "%Y-%m-%dT%H:%M:%S.%f")
    description = attributes.get("description", "")

    dataset = {
        "node_id": node["id"],
        "title": attributes["title"],
        "files_link": files_link,
        "components_list": components,
        "homepage": node["links"]["html"],
        "creators": [{"name": name} for name in contributors],
        "description": description,
        "wiki": wiki,
        "version": attributes["date_modified"],
        "licenses": [{"name": license_name}],
        "dates": [
            {
                "date": date_created.strftime("%Y-%m-%d %H:%M:%S"),
                "type": {"value": "date created"},
            },
            {
                "date": date_modified.strftime("%Y-%m-%d %H:%M:%S"),
                "type": {"value": "date modified"},
            },
        ],
        "keywords": keywords,
        "distributions": [
            {
                "size": 0,
                "unit": {"value": "B"},
                "access": {
                    "landingPage": node["links"]["html"],
                    "authorizations": [
                        {
                            "value": "public" if attributes.get("public") else "private",
                        }
                    ],
                },
            }
        ],
        "extraProperties": extra_properties,
        "isAbout": maybe_human_species(attributes["title"], description),
    }

    if identifier:
        dataset["identifier"] = {
            "identifier": identifier,
            "identifierSource": "OSF DOI" if "OSF.IO" in identifier.upper() else "DOI",
        }

    return dataset


def create_tracker(path: str, dataset: dict):
    with open(path, "w") as f:
        json.dump(
            {
                "osf": {
                    "node_id": dataset["node_id"],
                    "version": dataset["version"],
                },
                "title": dataset["title"],
            },
            f,
            indent=4,
        )


def write_readme(path: str, dataset: dict):
    content = f'# {dataset["title"]}\n\nCrawled from [OSF]({dataset["homepage"]})'
    if dataset.get("description"):
        content += f'\n\n## Description\n\n{html_to_text(dataset["description"])}'
    if dataset.get("identifier"):
        content += f'\n\n## DOI\n\n{dataset["identifier"]["identifier"]}'
    if dataset.get("wiki"):
        content += f'\n\n## Wiki\n\n{dataset["wiki"]}'
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
    parser = argparse.ArgumentParser(description="Import one OSF dataset into a local DataLad dataset.")
    parser.add_argument("--node", required=True, help="OSF node id or URL")
    parser.add_argument("--basedir", default=".", help="Base directory to create the dataset in (default: current directory)")
    parser.add_argument(
        "--config",
        default=os.path.expanduser("~/.conp_crawler_config.json"),
        help="Optional crawler config JSON used to read osf_token",
    )
    parser.add_argument(
        "--osf-token",
        help="OSF bearer token. Falls back to OSF_TOKEN, DATALAD_OSF_token, then config file",
    )
    args = parser.parse_args()

    node_id = normalize_node(args.node)
    token = load_osf_token(args.config, args.osf_token)

    node = fetch_json(f"https://api.osf.io/v2/nodes/{node_id}/", token)
    node_data = node["data"]
    dataset = build_description(node_data, token)

    dataset_dir = os.path.abspath(os.path.join(args.basedir, "projects", clean_title(dataset["title"])))

    ensure_dataset_dir(dataset_dir)
    ensure_osf_provider(dataset_dir, token)

    file_sizes: list[int] = []
    download_files(dataset["files_link"], dataset_dir, "", dataset_dir, token, file_sizes)
    if dataset["components_list"]:
        download_components(dataset["components_list"], dataset_dir, token, file_sizes)

    dataset_size, dataset_unit = natural_size(sum(file_sizes))
    dataset["distributions"][0]["size"] = dataset_size
    dataset["distributions"][0]["unit"]["value"] = dataset_unit

    create_tracker(os.path.join(dataset_dir, ".conp-osf-crawler.json"), dataset)
    write_readme(os.path.join(dataset_dir, "README.md"), dataset)
    write_dats(os.path.join(dataset_dir, "DATS.json"), dataset, dataset_dir)
    run(["git", "add", ".conp-osf-crawler.json", "README.md", "DATS.json"], cwd=dataset_dir)
    run(["datalad", "save", "-m", f"Import OSF node {node_id}"], cwd=dataset_dir)

    print(clean_title(dataset["title"]))
    print(dataset["title"])


if __name__ == "__main__":
    main()

