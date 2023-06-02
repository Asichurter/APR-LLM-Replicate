import subprocess as sp
import json
from typing import Dict
from apr_utils import load_json, load_text, dump_text, git_reset, git_clean, git_checkout
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

def run_d4j_test(repo_path):
    # compile_cmds = ['defects4j', 'compile']
    # compile_res = sp.run(compile_cmds, cwd=repo_path, capture_output=True)
    # compile_msg = compile_res.stdout.decode()
    compile_return_code, compile_err_lines = compile_repo(repo_path)
    if compile_return_code != 0:
        return -1, compile_err_lines, []

    test_cmds = ['defects4j', 'test']
    test_res = sp.run(test_cmds, cwd=repo_path, capture_output=True)
    test_msg = test_res.stdout.decode()
    ipdb.set_trace()
    if test_res.returncode != 0:
        return -2, test_msg, []
    # todo: check the output msg

    return 0, '', []


def d4j_test_generated_fix(tmp_repo_path, generated_path, buggy_hash, max_tries=10):
    generated_patches = load_json(generated_path)

    run_try_results = []
    for i in range(max_tries):
        # Clean work dir to recover buggy HEAD
        print(f"Try Patch {i+1}/{max_tries}")
        git_reset(tmp_repo_path)
        git_clean(tmp_repo_path)
        git_checkout(tmp_repo_path, buggy_hash, "buggy", strict_check=False)

        # Apply patch
        original_file_info = []
        for changed_file_patch in generated_patches:
            file_path, ori_file_cont, patched_file_cont = apply_file_patch(tmp_repo_path, changed_file_patch, i)
            original_file_info.append((file_path, ori_file_cont))

        # Run test
        test_status, test_msg, failed_tests = run_d4j_test(tmp_repo_path)
        if test_status == -1:
            print('Compile failed')
        elif test_status == 0:
            print('Test suit passed')
        run_try_results.append((test_status, test_msg, failed_tests))
        # todo: do with test results

        # # Revert changed files
        # for file_path, ori_file_content in original_file_info:
        #     dump_text(ori_file_content, file_path)

    plausible_patch_indices = []
    for i, (status_code, msg, failed_tests) in enumerate(run_try_results):
        if status_code == 0:
            print(f"# {i} passed all tests, regarded as a plausible patch")
            plausible_patch_indices.append(i)
    return plausible_patch_indices


if __name__ == '__main__':
    # repo_path = "/data2/zhijietang/temp/gson_2_buggy/"
    # generated_path = "/data2/zhijietang/temp/apr_test_diffs/d4j_gson_2_res.json"
    repo_path = "/tmp/gson_2_buggy"
    generated_path = "/home/user/data/apr_wdir/generated/d4j_gson_2_res.json"

    d4j_test_generated_fix(repo_path, generated_path, "D4J_Gson_2_BUGGY_VERSION", max_tries=200)