import os
import subprocess
from pprint import pprint
from tqdm import tqdm
import fire

from apr_utils import load_json, dump_json, git_export_diff

def extract_project_info(file_name):
    # incoder_1B_infill_Closure_1_test_result.json
    return file_name.split('_')[3], file_name.split('_')[4]

def aggregate_each_dump(individual_path, dump_path, dump_file_format: str):
    aggr = {}
    for each_file in os.listdir(individual_path):
        file_cont = load_json(os.path.join(individual_path, each_file))
        proj_id, bug_id = extract_project_info(each_file)
        if proj_id not in aggr:
            aggr[proj_id] = {}
        aggr[proj_id][f"{proj_id}-{bug_id}"] = file_cont
    for proj_id, aggregated in aggr.items():
        dump_file_path = os.path.join(dump_path, dump_file_format.format(proj_id))
        dump_json(aggregated, dump_file_path)


def count_plausible_patches(test_dump_base_path: str,
                            count_individual: bool = False,
                            individual_path: str = None):
    total_plausible_cnt = 0
    total_cnt = 0
    for filename in os.listdir(test_dump_base_path):
        file_path = os.path.join(test_dump_base_path, filename)
        if os.path.isdir(file_path):
            continue
        test_results = load_json(file_path)
        plausible_patches = []
        for bug_key, test_result in test_results.items():
            if len(test_result['plausible_patch_indices']) > 0:
                plausible_patches.append(bug_key)
        total_plausible_cnt += len(plausible_patches)
        total_cnt += len(test_results)
        print(f"{filename}: {len(plausible_patches)} / {len(test_results)}")
        print(plausible_patches)
        print('-'*75)
    print(f'Total plausible: {total_plausible_cnt} / {total_cnt}')

def count_d4j_bug():
    pid_cmd = ['defects4j', 'pids']
    pid_output = subprocess.run(pid_cmd, capture_output=True)
    pids = pid_output.stdout.decode().strip().split('\n')
    project_bug_cnts = {}
    for project in pids:
        bid_cmd = ['defects4j', 'bids', '-p', project]
        # print(' '.join(bid_cmd))
        bid_output = subprocess.run(bid_cmd, capture_output=True)
        project_bug_cnt = bid_output.stdout.decode().count('\n')
        project_bug_cnts[project] = project_bug_cnt
    print('\nbug count:\n')
    pprint(project_bug_cnts)
    print(f'\nTotal: {sum(project_bug_cnts.values())}')

# _libro_project_name_remap = {
#     "checkstyle_checkstyle": "checkstyle",
#     "google-gson": "gson",
#     "assertj_assertj": "assertj-core"
# }

def _extract_libro_project_name(name):
    no_owner = name.split("_")[1]
    no_id = "-".join(no_owner.split("-")[:-1])
    return no_id

def output_diff_for_libro_verified_bug(verified_bug_path='../data/GHRB/verified_bugs.json',
                                       project_base_path='/home/user/projects',
                                       output_base_path='/home/user/temp/libro_diff'):
    print(f"Outputing libro bug diff to {output_base_path}")
    verified_bugs = load_json(verified_bug_path)
    cnt = {}
    for key, bug in tqdm(verified_bugs.items()):
        project = _extract_libro_project_name(key)
        if project not in cnt:
            cnt[project] = 1
        bug_idx = cnt[project]
        cnt[project] += 1
        project_repo_path = os.path.join(project_base_path, project)
        buggy_hash = bug["buggy_commits"][0]["oid"]
        fixed_hash = bug["merge_commit"]
        git_export_diff(project_repo_path, buggy_hash, fixed_hash,
                        os.path.join(output_base_path, f"{project}-{fixed_hash}.diff"))

def commit_info(diff_path: str, project_base_path='/home/user/projects'):
    file_name = diff_path.split("/")[-1].split(".")[0]
    anchor = file_name.rindex('-')
    project = file_name[:anchor]
    commit = file_name[anchor+1:]
    output = subprocess.run(['git', 'show', commit, '-q'],
                            cwd=os.path.join(project_base_path, project),
                            capture_output=True)
    print(output.stdout.decode())

if __name__ == '__main__':
    fire.Fire()
    # aggregate_each_dump(individual_path='/home/user/results/plausible/d4j/each/',
    #                     dump_path='/home/user/results/plausible/d4j/',
    #                     dump_file_format='incoder_1B_infill_{}_test_results.json')
    # count_plausible_patches('/home/user/results/plausible/d4j/')
    # count_d4j_bug()
