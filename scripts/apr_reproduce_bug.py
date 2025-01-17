import json
import re
import time
from typing import Dict

from ghrb_util import fix_build_env
from apr_config import reproduce_config
from apr_utils import sp_call_helper, dump_json

import subprocess as sp
import argparse
import logging

from apr_bug_mine_re import extract_failed_file, extract_failure_method, extract_error_method

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
log_handler = logging.StreamHandler()
logger.addHandler(log_handler)

import ipdb

DEBUG = False

BUG_LIST_PATH = '/home/user/data/GHRB/verified_bugs.json'
CONFIG_PATH = '/home/user/data' # '/root/data/'


def enforce_static_assertions(gen_test):
    if 'Assert.' in gen_test:
        # force to use static assertion imports
        gen_test = gen_test.replace('Assert.fail', 'fail')
        gen_test = gen_test.replace('Assert.assert', 'assert')

    return gen_test


def compile_repo(repo_path):
    compile_proc = sp.run(['mvn', 'clean', 'compile', '--batch-mode',],
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
    assert cp.returncode == 0, f"checkout for {version} commit was not successful: {cp.stdout.decode() + ' | ' + cp.stderr.decode()}"
    out = sp.run(['git', 'rev-parse', 'HEAD'],
                 cwd=repo_path, capture_output=True)
    assert commit_hash in out.stdout.decode(
    ), f"checkout for {version} commit {commit_hash} was not successful: current commit is {out.stdout.decode()}"


def git_staged_diffs(repo_path):
    cp = sp.run(['git', 'diff', '--staged', '--name-only', '--relative'],
                cwd=repo_path, capture_output=True)
    assert cp.returncode == 0, f"'git diff --staged --name-only' failed in {repo_path}"

    return cp.stdout.decode().splitlines()


def overwrite_test_code(repo_path, overwrite_commit, test_dir='src/test/java'):
    # we need to synchronize test code (in merged version) same as the buggy version
    assert overwrite_commit is not None
    p = sp.run(['rm', '-rf', test_dir], cwd=repo_path)
    assert p.returncode == 0
    p = sp.run(['git', 'checkout', overwrite_commit,
                '--', test_dir], cwd=repo_path)
    assert p.returncode == 0


def extract_failed_tests_mvn(project_id, stdout: str):
    # Mvn Format:
    # -------------------------------------------------------------------------------------------
    # [INFO] Running com.puppycrawl.tools.checkstyle.checks.metrics.ClassFanOutComplexityCheckTest
    # [ERROR] Tests run: 23, Failures: 0, Errors: 2, Skipped: 0, Time elapsed: 0.12 s <<< FAILURE! - in com.puppycrawl.tools.checkstyle.checks.metrics.ClassFanOutComplexityCheckTest
    # [ERROR] testClassFanOutComplexityMultiCatchBitwiseOr  Time elapsed: 0.008 s  <<< ERROR!
    # [ERROR] testWithArrayCreateFullIdentWithArrayDeclare  Time elapsed: 0 s  <<< FAILURE!
    # -------------------------------------------------------------------------------------------
    failed_test = []
    lines = stdout.splitlines()
    failed_test_file = None
    for line in lines:
        line = line.strip()
        # Failed test file
        if "<<< FAILURE!" in line:
            failed_files = extract_failed_file(line)
            # New failed file found
            if len(failed_files) > 0:
                failed_test_filename = failed_files[0]
                # When found a new file, append last file
                if failed_test_file is not None:
                    failed_test.append(failed_test_file)
                failed_test_file = {
                    "failed_test_file": failed_test_filename,
                    "failure_test_method": [],
                    "error_test_method": [],
                }
            # New failed method found
            else:
                failure_method = extract_failure_method(line)
                if len(failure_method) == 0:
                    logger.error(f"No failure method extracted in failure line: '{line}'")
                elif failed_test_file is None:
                    logger.error(f"Failure method found before a test file found (is None): '{line}'")
                    failed_test_file = {
                        "failed_test_file": None,
                        "failure_test_method": failure_method,
                        "error_test_method": [],
                    }
                elif len(failure_method) > 1:
                    logger.warning(f"More than one failure method found: {failure_method}. Raw Line: '{line}'")
                else:
                    failed_test_file["failure_test_method"].append(failure_method[0])
        # New error method found
        elif "<<< ERROR!" in line:
            error_method = extract_error_method(line)
            if len(error_method) == 0:
                logger.error(f"No error method extracted in error line: '{line}'")
            elif failed_test_file is None:
                logger.error(f"Error method found before a test file found (is None): '{line}'")
                failed_test_file = {
                    "failed_test_file": None,
                    "failure_test_method": [],
                    "error_test_method": error_method,
                }
            elif len(error_method) > 1:
                logger.warning(f"More than one error method found: {error_method}. Raw Line: '{line}'")
            else:
                failed_test_file["error_test_method"].append(error_method[0])

    if failed_test_file is not None:
        failed_test.append(failed_test_file)

    return failed_test


def mvn_install_dependencies(repo_path):
    # Refer to Maven lifecycle: https://blog.csdn.net/qq_39505065/article/details/102915403
    cmd = ['mvn', 'clean', 'package', '--batch-mode', '-Dmaven.test.skip', '-Denforcer.skip=true']
    sp_call_helper(cmd, cwd=repo_path)

def run_test(repo_path, project_id, record={}, timeout='5m', extra_test_config=[], **kwargs):
    fix_build_env(repo_path)
    # Set --batch-mode to disable colored output
    run_command = ['timeout', f'{timeout}', 'mvn', 'test', '--batch-mode', '-Denforcer.skip=true']  # TODO: extend timeout for assertj
    # run_command = ['timeout', f'{timeout}', 'mvn', 'test', '--batch-mode']  # TODO: extend timeout for assertj

    # Extra configs
    if project_id == 'gson':
        run_command.extend(['-DfailIfNoTests=false'])
    if project_id == 'sslcontext':
        run_command.extend(['-pl', ":sslcontext-kickstart"])
    if project_id == 'checkstyle':
        run_command.extend(['-Djacoco.skip=true'])
    run_command.extend(extra_test_config)

    test_process = sp.run(run_command, capture_output=True, cwd=repo_path)

    captured_stdout = test_process.stdout.decode()
    captured_stderr= test_process.stderr.decode()
    record["stdout"] = captured_stdout
    record["stderr"] = captured_stderr

    if DEBUG:
        ipdb.set_trace()

    # Compile error
    captured_stdout_lower = captured_stdout.lower()
    if 'compilation failure' in captured_stdout_lower or 'compilation error' in captured_stdout_lower:
        return -2, []

    # If finally reports success, means no errors and failures
    if 'BUILD SUCCESS' in captured_stdout:
        return 0, []

    # No success message, but:
    # 1. Correctly exit
    # 2. Without any compile/test failures, something went wrong
    if len(captured_stdout) == 0 or ('<<< FAILURE!' not in captured_stdout and '<<< ERROR!' not in captured_stdout):
        return -1, []
    # if len(captured_stdout) == 0 or 'There are test failures' not in captured_stdout:

    failed_tests = extract_failed_tests_mvn(project_id, captured_stdout)

    # Check timeout
    if str(test_process.returncode) in ['123', '124']:
        logger.warning(f"Timeout triggerred ({timeout})")
        return -3, failed_tests

    if DEBUG:
        ipdb.set_trace()

    return 0, failed_tests


def get_test_execution_result(repo_path, project_id, commit_id, commit_type, **kwargs):
    record = {}
    status, failed_tests = run_test(
        repo_path, project_id, record=record, **kwargs)

    return {
        'commit_type': commit_type,
        'commit_id': commit_id,
        'compile_error': status == -2,
        'runtime_error': status == -1,
        'timeout': status == -3,
        'failed_tests': failed_tests,
        'run_succeed': status == 0,
        'test_passed': len(failed_tests) == 0,
        '__stdout': record['stdout'],
        '__stderr': record['stderr'],
    }


def individual_run(repo_path, project_id, commit_id, commit_type, **kwargs):
    start_time = time.time()
    exec_result = get_test_execution_result(repo_path, project_id, commit_id, commit_type, **kwargs)
    run_time = time.time() - start_time
    logger.info(f"Individual run timed: {run_time} s")
    return exec_result

def debug_print(msg, debug: bool):
    if debug:
        print(msg)

def check_run_failed(run_info: Dict):
    return not run_info['run_succeed'] or not run_info['test_passed'] or run_info['timeout']

def twover_run_experiment(repo_path, buggy_commit=None, fixed_commit=None,
                          project_id=None, test_dir='src/test/java', t_logger=None, **kwargs):
    if t_logger is None:
        t_logger = logger

    # Running experiment for buggy version
    t_logger.info('BugVer: Git Reset & Clean ...')
    git_reset(repo_path)
    git_clean(repo_path)

    t_logger.info(f'BugVer: Git Checkout to {buggy_commit} ...')
    git_checkout(repo_path, buggy_commit, version='buggy')
    fix_build_env(repo_path)
    t_logger.info('BugVer: Installing dependencies...')
    mvn_install_dependencies(repo_path)
    t_logger.info('BugVer: Compile ...')
    compile_success, compile_output = compile_repo(repo_path)
    if not compile_success:
        return -1, f"Buggy source Code Compilation failed: {buggy_commit}. Compiling output: {compile_output}"

    try:
        # git_reset(repo_path)
        # git_clean(repo_path)    # this should not delete class files
        # Use updated test suit
        t_logger.info('BugVer: Run test ...')
        overwrite_test_code(repo_path, fixed_commit, test_dir)
        buggy_info = individual_run(repo_path, project_id, buggy_commit, 'buggy', **kwargs)
    except Exception as e:
        buggy_info = f'[error] {repr(e)}'

    # Running experiment for fixed version
    t_logger.info('FixVer: Git Reset & Clean ...')
    git_reset(repo_path)
    git_clean(repo_path)

    t_logger.info(f'FixVer: Git Checkout to {fixed_commit} ...')
    git_checkout(repo_path, fixed_commit, version='fixed')
    fix_build_env(repo_path)
    t_logger.info('FixVer: Installing dependencies...')
    mvn_install_dependencies(repo_path)

    t_logger.info('FixVer: Compile ...')
    compile_success, compile_output = compile_repo(repo_path)
    if not compile_success:
        raise Exception(
            f"Fixed source Code Compilation failed: {fixed_commit}. Compiling output: {compile_output}")
    try:
        # git_reset(repo_path)
        # git_clean(repo_path)    # this should not delete class files
        # Make sure fixed version runs the same test code as buggy version
        # overwrite_test_code(repo_path, buggy_commit)
        t_logger.info('FixVer: Run test ...')
        fixed_info = individual_run(repo_path, project_id, fixed_commit, 'fixed', **kwargs)
    except Exception as e:
        fixed_info = f'[error] {repr(e)}'

    # # todo: Retry
    # if fixed_info['compile_error']:
    #     pass
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
            'buggy': None,
            'fixed': None,
            '_success': False,
            '_summary': f"buggy version raise exception: {buggy_info}"
        }
    elif isinstance(fixed_info, str):
        final_result = {
            'buggy': buggy_info,
            'fixed': None,
            '_success': False,
            '_summary': f"fixed version raise exception: {fixed_info}"
        }
    else:
        fails_in_buggy_version = check_run_failed(buggy_info)
        fails_in_fixed_version = check_run_failed(fixed_info)
        test_executable_in_fixed_version = fixed_info['run_succeed']
        success = (fails_in_buggy_version and
                   not fails_in_fixed_version and
                   test_executable_in_fixed_version)

        final_result = {
            'buggy': buggy_info,
            'fixed': fixed_info,
            '_success': success,
            '_summary': f"successfully runs, buggy_failed={fails_in_buggy_version}, fixed_failed={fails_in_fixed_version}, success: {success}"
        }

    final_result['project'] = project_id
    final_result['project_path'] = repo_path

    t_logger.info(f"{project_id}: {buggy_commit} / {fixed_commit} done")
    return final_result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--project', default='checkstyle')
    parser.add_argument('-b', '--bug_id', default=2134)
    parser.add_argument('--debug', action="store_true", default=False)
    # parser.add_argument('-n', '--test_no', type=int, default=None)
    # parser.add_argument('--gen_test_dir', default='/root/data/GHRB/gen_tests/')
    # parser.add_argument('--all', action='store_true')
    parser.add_argument('--exp_name', default='example2_n50_ghrb')
    args = parser.parse_args()

    with open(BUG_LIST_PATH) as f:
        data = json.load(f)

    DEBUG = args.debug
    # if args.test_no is None:
    if True:
        # test_files = glob.glob(os.path.join(GEN_TEST_DIR, f'{args.project}_{args.bug_id}_*.txt'))
        # example_tests = []
        res_for_bug = {}

        # for gen_test_file in test_files:
        #     with open(gen_test_file) as f:
        #         example_tests.append(f.read())

        # todo: debug
        repo_path = reproduce_config[args.project]['repo_path']
        src_dir = reproduce_config[args.project]['src_dir']
        test_prefix = reproduce_config[args.project]['test_prefix']
        project_name = reproduce_config[args.project]['project_name']
        project_id = reproduce_config[args.project]['project_id']
        # repo_path = '/home/user/projects/checkstyle/'
        # src_dir = 'src/main/java/'
        # test_prefix = 'src/test/java/'
        # project_name = 'checkstyle_checkstyle'
        # project_id = 'checkstyle'

        exp_kwargs = {
            'extra_test_configs': reproduce_config[args.project]['extra_test_config'],
            'timeout': reproduce_config[args.project]['timeout']
        }

        # test_files = collect_test_files(repo_path)

        # target_bug = data[f'{args.project}-{args.bug_id}']
        # todo: debug
        target_bug = data['checkstyle_checkstyle-10839']
        bug_no = target_bug['PR_number']
        # buggy_commit = target_bug['buggy_commits'][0]['oid']
        # fixed_commit = target_bug['merge_commit']
        buggy_commit = "c5acf2d3c6dda03c21ab9bcb121aaa0f53e00434"
        fixed_commit = "caa907fa69bc25490044bf9160681d1534f97f8b"

        results = twover_run_experiment(repo_path, buggy_commit, fixed_commit, project_id, test_prefix, **exp_kwargs)
        # print(results)
        print("Dump to /home/user/temp/reproduce_bug_output.json ...")
        dump_json(results, '/home/user/temp/reproduce_bug_output.json')

        # for test_path, res in zip(test_files, results):
        #     res_for_bug[os.path.basename(test_path)] = res

        # with open(f'/root/results/{args.exp_name}_{args.project}_{args.bug_id}.json', 'w') as f:
        #     json.dump(res_for_bug, f, indent=4)

        # print(res_for_bug)
