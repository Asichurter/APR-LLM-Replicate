import os
import subprocess as sp
from tqdm import tqdm

from apr_diff_extract import extract_changed_funcs_from_diff
from apr_prompts import build_infill_prompt_for_funcs
from incoder_infill import apr_infill
from apr_utils import load_text, dump_json, git_reset, git_clean, git_checkout, make_d4j_commit_hash

import ipdb

def infill_from_diff(diff_path, repeat_gen: int, buggy_commit, fix_commit, max_token_to_generate,
                     temperature: float = 0.8):
    # export_diff(repo_path, buggy_commit, fix_commit, diff_path)
    diff = load_text(diff_path)
    changed_files, ok = extract_changed_funcs_from_diff(diff)
    assert ok, f'Fail to extract chagned funcs from diff: {fix_commit} {buggy_commit}'

    results = []
    for changed_file in changed_files:
        if len(changed_file['changed_funcs']) != 1:
            print(f'[Warning] Not only one function changed detected for {changed_file["file"].path}: {len(changed_file["changed_funcs"])}.')

        print(f"\nInfilling {changed_file['file'].path} ...")
        changed_func_of_file = build_infill_prompt_for_funcs(changed_file['file'], changed_file['changed_funcs'], '<INFILL>')

        for changed_func in changed_func_of_file:
            generated = []
            for _ in tqdm(range(repeat_gen)):
                res = apr_infill(changed_func['func_prompt'], max_to_generate=max_token_to_generate, temperature=temperature)
                generated.append(res)
            changed_func['generated_result'] = generated

        results.append({
            'file_path': changed_file['file'].path,
            'changed_funcs': changed_func_of_file
        })

    return results


def apr_run_infill(tgt_diff_base_path: str, tgt_infill_base_path: str,
                   repeat_gen: int, max_token_to_gen: int,
                   temperature: float = 0.8,
                   vidx: int = None):
    selected_indices = sorted(os.listdir(tgt_diff_base_path))
    if vidx is not None:
        selected_indices = selected_indices[vidx*50:(vidx+1)*50]
    for i, diff_file_path in enumerate(selected_indices):
        # filename example: .../d4j_JacksonCore_12.diff
        print(f'# {i+1}/{len(selected_indices)} Infilling from {diff_file_path} ...')
        filename_splits = diff_file_path.split('/')[-1].split('.')[0].split('_')
        project_id, bug_id = filename_splits[1:]
        project_name = project_id
        diff_file_path = os.path.join(tgt_diff_base_path, f"d4j_{project_name}_{bug_id}.diff")
        buggy_hash = make_d4j_commit_hash(project_id, bug_id, "BUGGY_VERSION")
        fix_hash = make_d4j_commit_hash(project_id, bug_id, "FIXED_VERSION")

        infill_dump_path = os.path.join(tgt_infill_base_path, f"d4j_{project_name}_{bug_id}_infill.json")
        infill_res = infill_from_diff(diff_file_path, repeat_gen, buggy_hash, fix_hash, max_token_to_gen, temperature)
        dump_json(infill_res, infill_dump_path)
        # print(f'[Stage 3] Compiling and Testing ...')
        # plausible_patch_indices = d4j_test_generated_fix(repo_path, tgt_infill_base_path, buggy_hash, max_token_to_gen)
        # apr_results = {
        #     'meta_info': {
        #         'repo': repo_path,
        #         'buggy_hash': buggy_hash,
        #         'fix_hash': fix_hash,
        #         'repeat_gen': repeat_gen,
        #         'max_token_to_gen': max_token_to_gen,
        #         'temperature': temperature,
        #     },
        #     'input_and_generated': infill_res,
        #     'plausible_patch_indices': plausible_patch_indices
        # }
        # dump_json(apr_results, tgt_apr_result_path)

if __name__ == '__main__':
    # res_dump_path = '/data2/zhijietang/projects/libro/data/apr_wdir/generated/d4j_gson_2_res.json'
    #
    # buggy_commit = 'D4J_Gson_2_BUGGY_VERSION'
    # fix_commit = 'D4J_Gson_2_FIXED_VERSION'
    # repeat_generate_tries = 200
    # max_token_to_generate = 768
    #
    # test_diff_path = '/data2/zhijietang/projects/libro/data/apr_wdir/diff/d4j_gson_2.diff'
    # res = infill_from_diff(test_diff_path, repeat_generate_tries, buggy_commit, fix_commit, max_token_to_generate)
    # dump_json(res, res_dump_path)
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--volume', default=None)
    args = parser.parse_args()
    apr_run_infill(tgt_diff_base_path='/data2/zhijietang/projects/libro/data/apr_wdir/diff',
                   tgt_infill_base_path='/data2/zhijietang/projects/libro/data/apr_wdir/generated/incoder_infill',
                   repeat_gen=200,
                   max_token_to_gen=512,
                   temperature=0.8,
                   vidx=int(args.volume))