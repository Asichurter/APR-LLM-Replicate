import os
import json
import subprocess as sp
import shutil
from typing import List

import pandas

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

def read_csv_as_dict_list(path):
    data_frame = pandas.read_csv(path)
    columns = [k for k in data_frame.columns]
    rows = []
    for i, row in data_frame.iterrows():
        rows.append({
            k: row[k] for k in columns
        })
    return rows

def read_flat_csv_as_dict(path, key_index, has_header: bool = False):
    if has_header:
        data_frame = pandas.read_csv(path)
    else:
        data_frame = pandas.read_csv(path, header=None)
    result = {}
    for i, row in data_frame.iterrows():
        key_val = row[key_index]
        if key_val in result:
            print(f"[Warning] Duplicated key detected when reading csv: {key_val} from {path}. \nOverwriting ...")
        content = [row[i] for i in range(len(row)) if i != key_index]
        result[key_val] = content
    return result

def read_nocolumn_csv_as_dict(path, keys: List, main_key):
    data_frame = pandas.read_csv(path)
    assert main_key in keys
    main_key_index = keys.index(main_key)
    result = {}
    for row in data_frame.iterrows():
        main_key_val = row[main_key_index]
        if main_key_val in result:
            print(f"[Warning] Duplicated key detected when reading csv: {main_key_val} from {path}. \nOverwriting ...")
        content = {k:row[i] for i,k in enumerate(keys) if k != main_key}
        result[main_key_val] = content
    return result

def git_reset(repo_dir_path):
    sp.run(['git', 'reset', '--hard', 'HEAD'],
           cwd=repo_dir_path, stdout=sp.DEVNULL, stderr=sp.DEVNULL)


def git_clean(repo_dir_path):
    sp.run(['git', 'clean', '-df'],
           cwd=repo_dir_path, stdout=sp.DEVNULL, stderr=sp.DEVNULL)

def git_checkout(repo_path, commit_hash, version='buggy', strict_check=True, retry=0):
    """
        For tag checkout, strict check may fail and should be disabled.
    """
    while True:
        cp = sp.run(['git', 'checkout', commit_hash],
                    cwd=repo_path, capture_output=True)
        if cp.returncode != 0:
            print(f"checkout for {commit_hash} commit was not successful")
            if retry > 0:
                retry -= 1
                continue
            else:
                raise RuntimeError(f"checkout for {commit_hash} commit was not successful: " +
                                   f"{cp.stdout.decode() + ' | ' + cp.stderr.decode()}")
        if strict_check:
            out = sp.run(['git', 'rev-parse', 'HEAD'],
                         cwd=repo_path, capture_output=True)
            if commit_hash not in out.stdout.decode():
                raise RuntimeError(f"checkout for {version} commit {commit_hash} was not successful: current commit is {out.stdout.decode()}")
        return

def git_export_diff(repo_path: str, buggy_commit_hash: str, fix_commit_hash: str, output_path: str):
    cmds = ['git', 'diff', '--unified=100000', f'--output={output_path}', buggy_commit_hash, fix_commit_hash]
    sp_call_helper(cmds, cwd=repo_path)
    # export_output = sp.run(cmds, cwd=repo_path, capture_output=True)
    # output_msg = export_output.stdout.decode()
    # assert export_output.returncode == 0, f"Return code {export_output.returncode}: {output_msg}"
    # if output_msg != '':
    #     print(f'Git diff: {output_msg}')

def d4j_checkout(project_id, version, checkout_path):
    cmds = ['defects4j', 'checkout', '-p', project_id, '-v', version, '-w', checkout_path]
    sp_call_helper(cmds, retry=3)


def sp_call_helper(cmds, cwd=None, retry=None):
    retry = retry or 0
    while True:
        kwargs = {
            'capture_output': True,
        }
        if cwd is not None:
            kwargs['cwd'] = cwd
        res = sp.run(cmds, **kwargs)
        if res.returncode != 0:
            err_msg = f"Return code = {res.returncode}.\n Cmd: {' '.join(cmds)}\n " + \
                      f"stdout: {res.stdout.decode()}, stderr: {res.stderr.decode()}"
            if retry <= 0:
                raise RuntimeError(err_msg)
            else:
                print(f"[sp_call_helper] Cmd error: {err_msg}")
                print(f"Retry: {retry}")
                retry -= 1
                continue
        else:
            return


def make_d4j_commit_hash(project_id, bug_id, version: str):
    return f"D4J_{project_id}_{bug_id}_{version}"