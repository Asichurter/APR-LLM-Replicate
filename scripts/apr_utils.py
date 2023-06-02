import os
import json
import subprocess as sp
import shutil

def load_json(path):
    with open(path, 'r', encoding='UTF-8') as f:
        j = json.load(f)
    return j

def load_text(path):
    with open(path, 'r', encoding='UTF-8') as f:
        return f.read()

def dump_text(text, path):
    with open(path, 'w') as f:
        f.write(text)

def dump_json(obj, path, indent=4, sort=False):
    with open(path, 'w', encoding='UTF-8') as f:
        json.dump(obj, f, indent=indent, ensure_ascii=False, sort_keys=sort)

def rm_path(path: str):
    if os.path.exists(path):
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

def git_reset(repo_dir_path):
    sp.run(['git', 'reset', '--hard', 'HEAD'],
           cwd=repo_dir_path, stdout=sp.DEVNULL, stderr=sp.DEVNULL)


def git_clean(repo_dir_path):
    sp.run(['git', 'clean', '-df'],
           cwd=repo_dir_path, stdout=sp.DEVNULL, stderr=sp.DEVNULL)

def git_checkout(repo_path, commit_hash, version='buggy', strict_check=True):
    """
        For tag checkout, strict check may fail and should be disabled.
    """
    cp = sp.run(['git', 'checkout', commit_hash],
                cwd=repo_path, capture_output=True)
    assert cp.returncode == 0, "checkout for {version} commit was not successful"

    if strict_check:
        out = sp.run(['git', 'rev-parse', 'HEAD'],
                     cwd=repo_path, capture_output=True)
        assert commit_hash in out.stdout.decode(
        ), f"checkout for {version} commit {commit_hash} was not successful: current commit is {out.stdout.decode()}"

def git_export_diff(repo_path: str, buggy_commit_hash: str, fix_commit_hash: str, output_path: str):
    cmds = ['git', 'diff', '--unified=100000', f'--output={output_path}', fix_commit_hash, buggy_commit_hash]
    sp_call_helper(cmds, cwd=repo_path)
    # export_output = sp.run(cmds, cwd=repo_path, capture_output=True)
    # output_msg = export_output.stdout.decode()
    # assert export_output.returncode == 0, f"Return code {export_output.returncode}: {output_msg}"
    # if output_msg != '':
    #     print(f'Git diff: {output_msg}')

def d4j_checkout(project_id, version, checkout_path):
    cmds = ['defects4j', 'checkout', '-p', project_id, '-v', version, '-w', checkout_path]
    sp_call_helper(cmds)

def sp_call_helper(cmds, cwd=None):
    kwargs = {
        'capture_output': True,
    }
    if cwd is not None:
        kwargs['cwd'] = cwd
    res = sp.run(cmds, **kwargs)
    assert res.returncode == 0, f"Return code = {res.returncode}.\n Cmd: {' '.join(cmds)}\n stdout: {res.stdout.decode()}, stderr: {res.stderr.decode()}"

def make_d4j_commit_hash(project_id, bug_id, version: str):
    return f"D4J_{project_id}_{bug_id}_{version}"