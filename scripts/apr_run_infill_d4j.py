import subprocess as sp
import os
from tqdm import tqdm

from apr_utils import load_json, dump_json, d4j_checkout, rm_path, git_export_diff, make_d4j_commit_hash
from apr_test_generated import d4j_test_generated_fix

import ipdb


def apr_run_infill_gpu_machine(repo_path: str,
                               tgt_diff_path: str, tgt_infill_path: str, tgt_apr_result_path: str,
                               buggy_hash: str, fix_hash: str,
                               repeat_gen: int, max_token_to_gen: int,
                               temperature: float = 0.8):
    infill_res = load_json(tgt_infill_path)
    print(f'[Stage 3] Compiling and Testing ...')
    plausible_patch_indices = d4j_test_generated_fix(repo_path, tgt_infill_path, buggy_hash, max_token_to_gen)
    apr_results = {
        'meta_info': {
            'repo': repo_path,
            'buggy_hash': buggy_hash,
            'fix_hash': fix_hash,
            'repeat_gen': repeat_gen,
            'max_token_to_gen': max_token_to_gen,
            'temperature': temperature,
        },
        'input_and_generated': infill_res,
        'plausible_patch_indices': plausible_patch_indices
    }
    dump_json(apr_results, tgt_apr_result_path)

def apr_d4j_export_diffs(tgt_diff_path, temp_project_path: str = '/tmp/d4j_temp'):
    project_id_cmd = ['defects4j', 'pids']
    project_id_res = sp.run(project_id_cmd, capture_output=True)
    project_ids = project_id_res.stdout.decode().strip().split('\n')

    for i, project_id in enumerate(project_ids):
        print(f'Extracting bugs for #{i+1} {project_id}')
        project_name = project_id
        bug_id_cmd = ['defects4j', 'bids', '-p', project_id]
        bug_id_res = sp.run(bug_id_cmd, capture_output=True)
        active_bug_ids = bug_id_res.stdout.decode().strip().split('\n')

        # bug_ids = list(map(lambda x: int(s.strip()), bug_ids))
        for bug_id in tqdm(active_bug_ids):
            rm_path(temp_project_path)
            d4j_checkout(project_id, f'{bug_id}b', temp_project_path)
            buggy_hash = make_d4j_commit_hash(project_id, bug_id, "BUGGY_VERSION")
            fix_hash = make_d4j_commit_hash(project_id, bug_id, "FIXED_VERSION")
            diff_file_output_path = os.path.join(tgt_diff_path, f"d4j_{project_name}_{bug_id}.diff")
            git_export_diff(temp_project_path, buggy_hash, fix_hash, diff_file_output_path)

if __name__ == '__main__':
    apr_d4j_export_diffs(tgt_diff_path='/home/user/data/apr_wdir/diff')