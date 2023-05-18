from os import path
from common import collect_test_files, load_text, dump_text
from config import llm_exp_config
from collections import defaultdict
from tqdm import tqdm

import os
import re
import glob
import shutil
import glob
import json

from ghrb_util import license_sslcontext_kickstart, fix_build_env, pit, split_project_bug_id
from apr_config import config

import subprocess as sp
import argparse

import ipdb

DEBUG = True

BUG_LIST_PATH = '/root/data/GHRB/verified_bugs.json'
CONFIG_PATH = '/root/data/'


def enforce_static_assertions(gen_test):
    if 'Assert.' in gen_test:
        # force to use static assertion imports
        gen_test = gen_test.replace('Assert.fail', 'fail')
        gen_test = gen_test.replace('Assert.assert', 'assert')

    return gen_test


def compile_repo(repo_path):
    compile_proc = sp.run(['mvn', 'clean', 'compile'],
                          cwd=repo_path, capture_output=True)

    if compile_proc.returncode != 0:
        return (False, {
            'stdout': compile_proc.stdout.decode('utf-8'),
            'stderr': compile_proc.stderr.decode('utf-8')
        })

    return (True, {})


def remove_file(rel_filepath, repo_path):
    cp = sp.run(['rm', rel_filepath],
                cwd=repo_path, capture_output=True)
    assert cp.returncode == 0, "removing {rel_filepath} in {repo_path} was failed"


def git_reset(repo_dir_path):
    sp.run(['git', 'reset', '--hard', 'HEAD'],
           cwd=repo_dir_path, stdout=sp.DEVNULL, stderr=sp.DEVNULL)


def git_clean(repo_dir_path):
    sp.run(['git', 'clean', '-df'],
           cwd=repo_dir_path, stdout=sp.DEVNULL, stderr=sp.DEVNULL)


def git_checkout(repo_path, commit_hash, version='buggy'):
    cp = sp.run(['git', 'checkout', commit_hash],
                cwd=repo_path, capture_output=True)
    assert cp.returncode == 0, "checkout for {version} commit was not successful"
    out = sp.run(['git', 'rev-parse', 'HEAD'],
                 cwd=repo_path, capture_output=True)
    assert commit_hash in out.stdout.decode(
    ), f"checkout for {version} commit {commit_hash} was not successful: current commit is {out.stdout.decode()}"


def git_staged_diffs(repo_path):
    cp = sp.run(['git', 'diff', '--staged', '--name-only', '--relative'],
                cwd=repo_path, capture_output=True)
    assert cp.returncode == 0, f"'git diff --staged --name-only' failed in {repo_path}"

    return cp.stdout.decode().splitlines()


def overwrite_test_code(repo_path, buggy_commit, test_dir='src/test/java'):
    # we need to synchronize test code (in merged version) same as the buggy version
    assert buggy_commit is not None
    p = sp.run(['rm', '-rf', test_dir], cwd=repo_path)
    assert p.returncode == 0
    p = sp.run(['git', 'checkout', buggy_commit,
                '--', test_dir], cwd=repo_path)
    assert p.returncode == 0

def parse_test_std_output(project_id, stdout):
    # todo: parse std output of test for specific project
    return []


def run_test(repo_path, project_id, record={}, record_key='stdout', timeout=5, extra_test_config=[], **kwargs):
    fix_build_env(repo_path)
    # todo: This implementation is designed for single test. However, we only focus on global test of all the test samples.
    #       Thus we can use "mvn test" without giving "Dtest" param.
    run_command = ['timeout', f'{timeout}m', 'mvn', 'test', '-Denforcer.skip=true']  # TODO: extend timeout for assertj

    # Extra configs
    if 'gson' in repo_path:
        run_command.extend(['-DfailIfNoTests=false'])
    if 'sslcontext' in repo_path:
        run_command.extend(['-pl', ":sslcontext-kickstart"])
    if 'checkstyle' in repo_path:
        run_command.extend(['-Djacoco.skip=true'])
    run_command.extend(extra_test_config)

    test_process = sp.run(run_command, capture_output=True, cwd=repo_path)

    captured_stdout = test_process.stdout.decode()
    record[record_key] = captured_stdout

    if DEBUG:
        ipdb.set_trace()

    captured_stdout_lower = captured_stdout.lower()
    if 'compilation failure' in captured_stdout_lower or 'compilation error' in captured_stdout_lower:
        return -2, []

    # TODO: Why return after sucessful build?
    if 'BUILD SUCCESS' in captured_stdout:
        return 0, []

    # TODO: Run-time error matching should be adapted.
    # if len(captured_stdout) == 0 or 'There are test failures' not in captured_stdout:
    if len(captured_stdout) == 0 or ('<<< FAILURE!' not in captured_stdout and '<<< ERROR!' not in captured_stdout):
        return -1, []  # no compile/test failures, but something went wrong

    # todo: Parse the output to return detailed info about failured test methods.
    failed_tests = parse_test_std_output(project_id, captured_stdout)

    # for i, line in enumerate(output_lines):
    #     if 'AutoGen' in line and '<<< FAILURE!' in line and 'Failures:' not in line:
    #         failed_tests.append(line.split()[1])
    #     if 'AutoGen' in line and '<<< ERROR!' in line and 'Failures:' not in line:
    #         failed_tests.append(line.split()[1].split('(')[0])

    return 0, failed_tests


def get_test_execution_result(repo_path, project_id, commit_id, commit_type, **kwargs):
    record = {}
    status, failed_tests = run_test(
        repo_path, project_id, record=record, record_key='stdout', **kwargs)

    return {
        'commit_type': commit_type,
        'commit_id': commit_id,
        'compile_error': status == -2,
        'runtime_error': status == -1,
        'failed_tests': failed_tests,
        # todo: Failed test flag should be adapted
        'autogen_failed': status != 0, # len(failed_tests) > 0,
        'stdout': record['stdout']
    }


def individual_run(repo_path, project_id, commit_id, commit_type, **kwargs):
    return get_test_execution_result(repo_path, project_id, commit_id, commit_type, **kwargs)


def twover_run_experiment(repo_path, buggy_commit=None, fixed_commit=None,
                          project_id=None, **kwargs):
    # Running experiment for buggy version
    if DEBUG:
        print('BugVer: Git Reset & Clean ...')
    git_reset(repo_path)
    git_clean(repo_path)

    if DEBUG:
        print(f'BugVer: Git Checkout to {buggy_commit} ...')
    git_checkout(repo_path, buggy_commit, version='buggy')
    fix_build_env(repo_path)
    if DEBUG:
        print('BugVer: Compile ...')
    compile_success, compile_output = compile_repo(repo_path)
    if not compile_success:
        raise Exception(
            f"Buggy source Code Compilation failed: {buggy_commit}. Compiling output: {compile_output}")

    try:
        git_reset(repo_path)
        git_clean(repo_path)    # this should not delete class files
        buggy_info = individual_run(repo_path, project_id, 'buggy', **kwargs)
    except Exception as e:
        buggy_info = f'[error] {repr(e)}'

    # Running experiment for fixed version
    if DEBUG:
        print('FixVer: Git Reset & Clean ...')
    git_reset(repo_path)
    git_clean(repo_path)

    if DEBUG:
        print(f'FixVer: Git Checkout to {fixed_commit} ...')
    git_checkout(repo_path, fixed_commit, version='fixed')
    fix_build_env(repo_path)

    if DEBUG:
        print('FixVer: Compile ...')
    compile_success, compile_output = compile_repo(repo_path)
    if not compile_success:
        raise Exception(
            f"Fixed source Code Compilation failed: {fixed_commit}. Compiling output: {compile_output}")

    try:
        git_reset(repo_path)
        git_clean(repo_path)    # this should not delete class files
        # Make sure fixed version runs the same test code as buggy version
        overwrite_test_code(repo_path, buggy_commit)
        fixed_info = individual_run(repo_path, project_id, fixed_commit, 'fixed', **kwargs)
    except Exception as e:
        fixed_info = f'[error] {repr(e)}'

    # todo: Retry
    if fixed_info['compile_error']:
        pass
        # retry by discarding changes in the test code
        # test_name, file_content = fixed_info['testclass']
        # injected_test_class = os.path.join(
        #     test_prefix, test_name.split('#')[0].replace('.', '/') + '.java')
        #
        # changed_test_classes = git_staged_diffs(repo_path)
        # for tc in changed_test_classes:
        #     if tc != injected_test_class:
        #         remove_file(tc, repo_path)
        #
        # fixed_info = get_test_execution_result(
        #     repo_path, test_name, file_content)

    if isinstance(buggy_info, str):  # Test is syntactically incorrect (JavaSyntaxError)
        final_result = {
            'buggy': buggy_info,
            'fixed': None,
            '_success': False,
            '_summary': "test is syntactically incorrect (JavaSyntaxError like)"
        }
    elif fixed_info is None:
        final_result = {
            'buggy': buggy_info,
            'fixed': fixed_info,
            '_success': False,
            '_summary': "fixed version is None (Not possible this)"
        }
    else:
        # fails_in_buggy_version = any(
        #     map(lambda x: 'AutoGen' in x, buggy_info['failed_tests']))
        #
        # fails_in_fixed_version = any(
        #     map(lambda x: 'AutoGen' in x, fixed_info['failed_tests']))
        # TODO: Adapt here to check whether any tests failed
        fails_in_buggy_version = True
        fails_in_fixed_version = False
        test_executable_in_fixed_version = fixed_info['compile_error'] == False \
                                           and fixed_info['runtime_error'] == False
        success = (
                fails_in_buggy_version and not fails_in_fixed_version and test_executable_in_fixed_version)

        final_result = {
            'buggy': buggy_info,
            'fixed': fixed_info,
            'success': success,
            '_summary': f"successfully runs and result is {success}"
        }

    return final_result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--project', default='checkstyle_checkstyle')
    parser.add_argument('-b', '--bug_id', default=2134)
    # parser.add_argument('-n', '--test_no', type=int, default=None)
    # parser.add_argument('--gen_test_dir', default='/root/data/GHRB/gen_tests/')
    # parser.add_argument('--all', action='store_true')
    parser.add_argument('--exp_name', default='example2_n50_ghrb')
    args = parser.parse_args()

    with open(BUG_LIST_PATH) as f:
        data = json.load(f)

    # GEN_TEST_DIR = args.gen_test_dir

    # if args.all:
    #     assert args.project is not None  # target project should be set
    #
    #     bug2tests = defaultdict(list)
    #
    #     for gen_test_file in glob.glob(os.path.join(GEN_TEST_DIR, '*.txt')):
    #         bug_key = '_'.join(os.path.basename(gen_test_file).split('_')[:-2])
    #         project, bug_id = split_project_bug_id(bug_key)
    #         if project != args.project:
    #             continue
    #
    #         bug2tests[bug_key].append(gen_test_file)
    #
    #     exec_results = {}
    #     for bug_key, tests in tqdm(bug2tests.items()):
    #         project, bug_id = split_project_bug_id(bug_key)
    #         bug_id = int(bug_id)
    #         res_for_bug = {}
    #
    #         example_tests = []
    #         for test_file in tests:
    #             with open(test_file) as f:
    #                 example_tests.append(f.read())
    #
    #         repo_path = config[project]['repo_path']
    #         src_dir = config[project]['src_dir']
    #         test_prefix = config[project]['test_prefix']
    #         project_name = config[project]['project_name']
    #         project_id = config[project]['project_id']
    #
    #         target_bug = data[f'{project}-{bug_id}']
    #         bug_no = target_bug['PR_number']
    #         buggy_commit = target_bug['buggy_commits'][0]['oid']
    #         fixed_commit = target_bug['merge_commit']
    #
    #         results = twover_run_experiment(repo_path, src_dir, test_prefix, example_tests, buggy_commit, fixed_commit,
    #                                         project_id)
    #
    #         for test_path, res in zip(tests, results):
    #             res_for_bug[os.path.basename(test_path)] = res
    #         exec_results[bug_key] = res_for_bug
    #
    #         with open(f'results/{args.exp_name}_{args.project}.json', 'w') as f:
    #             json.dump(exec_results, f, indent=4)

    # if args.test_no is None:
    if True:
        # test_files = glob.glob(os.path.join(GEN_TEST_DIR, f'{args.project}_{args.bug_id}_*.txt'))
        # example_tests = []
        res_for_bug = {}

        # for gen_test_file in test_files:
        #     with open(gen_test_file) as f:
        #         example_tests.append(f.read())

        # todo: debug
        # repo_path = config[args.project]['repo_path']
        # src_dir = config[args.project]['src_dir']
        # test_prefix = config[args.project]['test_prefix']
        # project_name = config[args.project]['project_name']
        # project_id = config[args.project]['project_id']
        repo_path = '/root/data/GHRB/repos/checkstyle/'
        src_dir = 'src/main/java/'
        test_prefix = 'src/test/java/'
        project_name = 'checkstyle_checkstyle'
        project_id = 'checkstyle'

        exp_kwargs = {
            'extra_test_configs': config[args.project]['extra_test_config'],
        }

        # test_files = collect_test_files(repo_path)

        # target_bug = data[f'{args.project}-{args.bug_id}']
        # todo: debug
        target_bug = data['checkstyle_checkstyle-10839']
        bug_no = target_bug['PR_number']
        buggy_commit = target_bug['buggy_commits'][0]['oid']
        fixed_commit = target_bug['merge_commit']

        results = twover_run_experiment(repo_path, buggy_commit, fixed_commit, project_id, **exp_kwargs)

        # for test_path, res in zip(test_files, results):
        #     res_for_bug[os.path.basename(test_path)] = res

        # with open(f'/root/results/{args.exp_name}_{args.project}_{args.bug_id}.json', 'w') as f:
        #     json.dump(res_for_bug, f, indent=4)

        # print(res_for_bug)

    else:
        raise ValueError
        # with open(os.path.join(GEN_TEST_DIR, f'{args.project}_{args.bug_id}_markdown_n{args.test_no}.txt')) as f:
        #     example_test = f.read()
        #
        # repo_path = config[args.project]['repo_path']
        # src_dir = config[args.project]['src_dir']
        # test_prefix = config[args.project]['test_prefix']
        # project_name = config[args.project]['project_name']
        # project_id = config[args.project]['project_id']
        #
        # target_bug = data[f'{args.project}-{args.bug_id}']
        # bug_no = target_bug['PR_number']
        # buggy_commit = target_bug['buggy_commits'][0]['oid']
        # fixed_commit = target_bug['merge_commit']
        #
        # # example experiment execution
        # print(twover_run_experiment(repo_path, src_dir, test_prefix, [example_test], buggy_commit, fixed_commit,
        #                             project_id))
