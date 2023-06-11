import subprocess as sp
import time
from typing import Dict
from apr_utils import load_json, load_text, dump_text, dump_json, git_reset, git_clean, git_checkout, d4j_checkout, rm_path
from tqdm import tqdm

import ipdb

def compile_repo(repo_dir_path):
    # actual compiling
    compile_proc = sp.run(
        ['defects4j', 'compile'],
        stdout=sp.PIPE, stderr=sp.PIPE, cwd=repo_dir_path)

    # extracting error message
    compile_error_lines = compile_proc.stderr.decode('utf-8').split('\n')[2:]
    compile_error_lines = [
        e for e in compile_error_lines if '[javac] [' not in e]
    compile_error_lines = [e for e in compile_error_lines if '[javac]' in e]
    compile_error_lines = [
        e for e in compile_error_lines if 'warning:' not in e]
    compile_error_lines = [
        e for e in compile_error_lines if '[javac] Note:' not in e]
    compile_error_lines = [
        e for e in compile_error_lines if 'compiler be upgraded.' not in e]
    compile_error_msg = '\n'.join(compile_error_lines)
    return compile_proc.returncode, compile_error_msg

def convert_d4j_file_abs_path(repo_path, file_path):
    # relative_path = '/'.join(file_path.split('/')[1:])
    relative_path = file_path
    if repo_path[-1] != '/':
        return repo_path + '/' + relative_path
    else:
        return repo_path + relative_path

def apply_file_patch(repo_path: str, file_patch: Dict, gen_index: int):
    file_path = file_patch["file_path"]
    file_abs_path = convert_d4j_file_abs_path(repo_path, file_path)
    original_file_content = load_text(file_abs_path)
    funcs = sorted(file_patch["changed_funcs"], key=lambda x: x["line_range"][0])

    cur_line = 0
    patched_file_cont = ''
    file_lines = original_file_content.split('\n')
    for func in funcs:
        line_start, line_end = func['line_range']
        # Add part of no change
        while cur_line < line_start:
            patched_file_cont += file_lines[cur_line] + '\n'
            cur_line += 1
        patched_file_cont += func["generated_result"][gen_index]
        cur_line = line_end + 1
    # Add tail
    while cur_line < len(file_lines):
        patched_file_cont += file_lines[cur_line] + '\n'
        cur_line += 1

    dump_text(patched_file_cont, file_abs_path)

    return file_abs_path, original_file_content, patched_file_cont

def extract_failed_tests(stdout: str):
    stdout_lines = stdout.strip().split('\n')
    # No failing tests extracted
    if 'Failing tests:' not in stdout_lines[0]:
        return None, []
    failed_test_num = int(stdout_lines[0].removeprefix('Failing tests: '))
    failed_tests = [e.strip(' - ') for e in stdout_lines[1:] if len(e) > 1]
    return failed_test_num, failed_tests

def run_d4j_test(repo_path, timeout=None):
    # compile_cmds = ['defects4j', 'compile']
    # compile_res = sp.run(compile_cmds, cwd=repo_path, capture_output=True)
    # compile_msg = compile_res.stdout.decode()
    compile_return_code, compile_err_lines = compile_repo(repo_path)
    # -1: Compile error
    if compile_return_code != 0:
        return -1, compile_err_lines, []

    test_cmds = ['defects4j', 'test']
    if timeout:
        test_cmds = ['timeout', f'{timeout}'] + test_cmds
    test_res = sp.run(test_cmds, cwd=repo_path, capture_output=True)
    test_msg = test_res.stdout.decode()
    # ipdb.set_trace()
    # -2: Unknown unexpected exit
    if test_res.returncode != 0:
        return -2, test_msg, []
    failed_test_num, failed_tests = extract_failed_tests(test_msg)
    # -3: Test failed
    if failed_test_num is not None and failed_test_num != 0:
        return -3, test_msg, failed_tests
    # todo: check the output msg

    return 0, test_msg, failed_tests


def d4j_test_generated_fix(tmp_repo_path, generated_path, buggy_hash, max_tries=10,
                           verbose=True, ignore_if_passed: bool = True, timeout=None):
    generated_patches = load_json(generated_path)

    run_try_results = []
    any_passed = False
    bar = range(max_tries)
    if not verbose:
        bar = tqdm(bar)

    for i in bar:
        if verbose:
            print(f"Patch #{i+1}/{max_tries}", end=' —— ', flush=True)
        if any_passed and ignore_if_passed:
            if verbose:
                print("Ignored as any passed")
            run_try_results.append((1, 'Ignored', []))
            continue
        try:
            # Clean work dir to recover buggy HEAD
            git_reset(tmp_repo_path)
            git_clean(tmp_repo_path)
            git_checkout(tmp_repo_path, buggy_hash, "buggy", strict_check=False, retry=3)

            # Apply patch
            original_file_info = []
            for changed_file_patch in generated_patches:
                file_path, ori_file_cont, patched_file_cont = apply_file_patch(tmp_repo_path, changed_file_patch, i)
                original_file_info.append((file_path, ori_file_cont))

            # Run test
            start_time = time.time()
            test_status, test_msg, failed_tests = run_d4j_test(tmp_repo_path, timeout=timeout)
            end_time = time.time()
            time_to_test = end_time - start_time
            if verbose:
                if test_status == -1:
                    print('[Warning] Compile failed')
                elif test_status == -2:
                    print(f'[Error] Unknown unexpected exit (maybe timeout)')
                elif test_status == -3:
                    print(f'[Error] Test failed, failed tests ({len(failed_tests)}) : {failed_tests[:3]}' + f"{' ...' if len(failed_tests) > 3 else ''}")
                elif test_status == 0:
                    print('[Info] Test suit passed')
                if time_to_test > 10:
                    time_prefix = '[Warning]'
                else:
                    time_prefix = '[Debug]'
                print(f"{time_prefix} Test time: {round(time_to_test, 1)} s")
            if test_status == 0:
                any_passed = True
            run_try_results.append((test_status, test_msg, failed_tests))
        except Exception as e:
            print(f'[Error] Run-time failure for {project}-{bug_id}: {e}\n\n')

    plausible_patch_indices = []
    print(f"\nFinal Result:")
    for i, (status_code, msg, failed_tests) in enumerate(run_try_results):
        if status_code == 0:
            if verbose:
                print(f"Patch #{i} passed all tests, regarded as a plausible patch")
            plausible_patch_indices.append(i)
    return plausible_patch_indices, run_try_results

config = {
    'd4j': {
        'incoder_1B_infill': {
            'generated_base_path': '/home/user/data/apr_wdir/generated/incoder_infill',
            'generated_file_temp': 'd4j_{}_{}_infill.json',
            'results_dump_base_path': '/home/user/data/apr_wdir/result/d4j',
            'buggy_commit_temp': "D4J_{}_{}_BUGGY_VERSION",
            'max_tries': 200,
            'tmp_dir_temp': '/home/user/temp/d4j_tmp_{}',
            'timeout': '3m',
            'verbose': True
        }
    }
}

def d4j_main(args):
    projects = args.projects.split(',')
    dataset = args.dataset
    model = args.model

    generated_base_path = config[dataset][model]['generated_base_path']
    generated_file_temp = config[dataset][model]['generated_file_temp']
    results_dump_path = config[dataset][model]['results_dump_base_path'] + f'{model + "_" + "_".join(projects)}_test_results.json'
    buggy_commit_temp = config[dataset][model]['buggy_commit_temp']
    max_tries = config[dataset][model]['max_tries']
    tmp_dir_temp = config[dataset][model]['tmp_dir_temp']
    timeout = config[dataset][model]['timeout']

    results = {}
    for project in projects:
        print(f'Running: {project} ...')
        project_id = project
        project_name = project_id.lower()
        bug_id = 1
        tmp_dir = tmp_dir_temp.format(project)

        while True:
            generated_path = os.path.join(generated_base_path, generated_file_temp.format(project_id, bug_id))
            if not os.path.exists(generated_path):
                if bug_id >= 1000:
                    break
                else:
                    bug_id += 1
                    continue
            rm_path(tmp_dir)
            print(f"Checkout {bug_id}b ...")
            d4j_checkout(project_id, f'{bug_id}b', tmp_dir)
            buggy_commit = buggy_commit_temp.format(project_id, bug_id)
            print(f'Test bug {project_id}-{bug_id} ...')
            plausible_patch_indices, project_bug_full_results = d4j_test_generated_fix(tmp_dir, generated_path,
                                                                                       buggy_commit,
                                                                                       max_tries=max_tries,
                                                                                       verbose=config[dataset][model]['verbose'],
                                                                                       ignore_if_passed=False,
                                                                                       timeout=timeout)
            bug_key = f'{project_name}-{bug_id}'
            results[bug_key] = {
                'generated_path': generated_path,
                'plausible_patch_indices': plausible_patch_indices,
                'full_results': project_bug_full_results,
            }
            bug_id += 1
            print('-' * 50)

    dump_json(results, results_dump_path)


if __name__ == '__main__':
    # # repo_path = "/data2/zhijietang/temp/gson_2_buggy/"
    # # generated_path = "/data2/zhijietang/temp/apr_test_diffs/d4j_gson_2_res.json"
    # repo_path = "/tmp/compress_47_buggy"
    # generated_path = "/home/user/data/apr_wdir/generated/incoder_infill/d4j_Compress_47_infill.json"
    #
    # plausible_patch_indices, _ = d4j_test_generated_fix(repo_path, generated_path, "D4J_Compress_47_BUGGY_VERSION", max_tries=200)
    # print(f"Plausible patch indices: {plausible_patch_indices}")

    import os
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--projects', default='Math')
    # parser.add_argument('-t', '--title', default='incoder_infill')
    parser.add_argument('-d', '--dataset', default='d4j')
    parser.add_argument('-m', '--model', default='incoder_1B_infill')
    args = parser.parse_args()
    d4j_main(args)
