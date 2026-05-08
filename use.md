


python3 ./scripts/import_single_osf_to_local_datalad.py --node mhq3f --basedir /data/crawler/push_new_repo/conp-dataset-main/
python3 ./scripts/push_to_github.py --record mhq3f --pr --main-repo /data/crawler/push_new_repo/conp-dataset-main/



~/.conp_crawler_config.json


{
    "osf_token": "你的_OSF_访问令牌",
    "zenodo_token": "你的_Zenodo_访问令牌"
}