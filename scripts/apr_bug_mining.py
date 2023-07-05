from typing import List, Dict
import logging
import os
import unidiff

from apr_utils import read_csv_as_dict_list, git_export_diff, dump_json, load_text, read_flat_csv_as_dict
from apr_reproduce_bug import twover_run_experiment
from apr_config import bug_mining_config
from apr_diff_extract import extract_changed_funcs_from_diff

DEBUG = False

if DEBUG:
    import ipdb

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
log_handler = logging.StreamHandler()
logger.addHandler(log_handler)

def mine_project_bugs(project_id: str,
                      bug_candidates: List[Dict],
                      project_layouts: Dict,
                      mining_result_dump_base_path: str,
                      mining_diff_dump_base_path: str,
                      overwrite: bool = True,
                      default_test_dir: str = 'src/main/java',
                      default_src_dir: str = 'src/test/java'):
    project_extra_test_args = bug_mining_config[project_id]["reproduction"]["extra_test_config"]
    project_test_timeout = bug_mining_config[project_id]["reproduction"]["timeout"]
    twoover_extra_args = {
        'extra_test_configs': project_extra_test_args,
        'timeout': project_test_timeout
    }
    # --------------------------------------------------------------------------------
    # bug struct:
    # [{'bug.id', 'revision.id.buggy', 'revision.id.fixed', 'report.id', 'report.url'}]
    # project struct:
    # ['hash': {'src_relative_path', 'test_relative_path'}]
    # --------------------------------------------------------------------------------
    for i, bug in enumerate(bug_candidates):
        prefix_commit = bug["revision.id.buggy"]
        postfix_commit = bug["revision.id.fixed"]
        repo_path = bug_mining_config[project_id]["repo_path"]
        # Get src & test dir
        try:
            prefix_src_path, prefix_test_path = project_layouts[prefix_commit]
            postfix_src_path, postfix_test_path = project_layouts[postfix_commit]
        except KeyError:
            prefix_src_path, prefix_test_path = default_src_dir, default_test_dir
            postfix_src_path, postfix_test_path = default_src_dir, default_test_dir

        try:
            logger.info("\n\n" + "#"*75 + f"\nChecking {project_id} #{i}: {prefix_commit} - {postfix_commit} ...\n" + "#"*75)
            diff_path = os.path.join(mining_diff_dump_base_path,
                                     f"{project_id}_{i}_{prefix_commit}_{postfix_commit}.diff")
            git_export_diff(repo_path, prefix_commit, postfix_commit, diff_path)

            if prefix_test_path != postfix_test_path:
                logger.warning(f"#{i}: prefix_test_path != postfix_test_path: {prefix_test_path, postfix_test_path}, skipped")
                continue
            bug_result_dump_path = os.path.join(mining_result_dump_base_path,
                                                f"{project_id}_{i}_{prefix_commit}_{postfix_commit}_mine_result.json")
            if not overwrite and os.path.exists(bug_result_dump_path):
                logger.warning(f"Bug result exist: {bug_result_dump_path}, skipped")
                continue

            logger.info("Executing two-over experiment ...")
            reproduction_result = twover_run_experiment(repo_path, prefix_commit, postfix_commit, project_id, prefix_test_path,
                                                   **twoover_extra_args)
            logger.info("Parsing diff size ...")
            size_result = parse_diff_size(diff_path)
            final_result = {
                "project": project_id,
                "info": {
                    "index": i,
                    "prefix_commit": prefix_commit,
                    "postfix_commit": postfix_commit,
                    "issue_id": bug["report.id"],
                    "issue_url": bug["report.url"],
                },
                "size": size_result,
                "reproduction": reproduction_result,
            }
            dump_json(bug_result_dump_path, final_result)
            logger.info(f"Dumping {project_id} #{i} to {bug_result_dump_path} ...")

        except Exception as e:
            logger.error(f"Error for {project_id} #{i}: {prefix_commit} - {postfix_commit}: {e}")

        # todo: remove
        if i == 10:
            return

import ipdb

def parse_diff_size(diff_path,
                    test_prefix: str = 'src/test/java',
                    src_prefix: str = 'src/main/java'):
    diff_cont = load_text(diff_path)
    patch = unidiff.PatchSet(diff_cont)
    hunks = []
    type_to_index = {'test': 0, 'src': 1, 'other': 2}

    # File & changed func stat
    file_type_cnts = [0, 0, 0]
    changed_func_cnts = [0, 0, 0]
    changed_funcs = []
    for file in patch:
        f_path: str = file.path
        file_type = 'other'
        if f_path.startswith(test_prefix):
            file_type = 'test'
        elif f_path.startswith(src_prefix):
            file_type = 'src'
        file_type_index = type_to_index[file_type]
        file_type_cnts[file_type_index] += 1

        # changed func within file
        f_changed_funcs, ok = extract_changed_funcs_from_diff(str(file), sig_only=True)
        if ok:
            changed_func_cnts[file_type_index] += len(f_changed_funcs)
            # Only one file
            for func in f_changed_funcs[0]["changed_funcs"]:
                # Signature only
                changed_funcs.append(func)

        # Add hunk
        for hunk in file:
            hunks.append({
                'type': file_type,
                'hunk': hunk
            })

    # Hunk & Line stat
    hunk_type_cnts = [0, 0, 0]
    add_loc_cnts = [0, 0, 0]
    del_loc_cnts = [0, 0, 0]
    for hunk in hunks:
        hunk_type = hunk["type"]
        cnt_index = type_to_index[hunk_type]
        hunk_type_cnts[cnt_index] += 1
        # ipdb.set_trace()
        add_loc_cnts[cnt_index] += hunk['hunk'].added
        del_loc_cnts[cnt_index] += hunk['hunk'].removed

    size_result = {
        "file": reformat_count(type_to_index, file_type_cnts),
        "hunk": reformat_count(type_to_index, hunk_type_cnts),
        "line": {
            "added": reformat_count(type_to_index, add_loc_cnts),
            "removed": reformat_count(type_to_index, del_loc_cnts),
        },
        "changed_function": reformat_count(type_to_index, changed_func_cnts),
        "changed_function_detail": changed_funcs,
    }
    size_result['test_added'] = size_result["line"]["added"]["test"] > 0
    return size_result

def reformat_count(type_to_index: Dict,
                   counts: List):
    """
        Convert the list counts to named dict format:
        e.g.:
            [5, 12, 50] + {'test': 0, 'src': 1, 'other': 2}
                        ↓
                {'test': 5, 'src': 12, 'other': 50}
    """
    index_2_type = {v:k for k,v in type_to_index.items()}
    return {
        index_2_type[i]: counts[i] for i in range(len(counts))
    }

# def stat_file_info(file,
#                    test_prefix: str,
#                    src_prefix: str):
#     hunks = []
#     f_path: str = file.path
#     file_type = 'none'
#     is_test, is_src, is_other = 0, 0, 0
#     if f_path.startswith(test_prefix):
#         is_test += 1
#         file_type = 'src'
#     elif f_path.startswith(src_prefix):
#         is_src += 1
#         file_type = 'test'
#     else:
#         is_other += 1
#     # Add hunk
#     for hunk in file:
#         hunks.append({
#             'type': file_type,
#             'hunk': hunk
#         })
#     return hunks, is_test, is_src, is_other
#
# def stat_hunk_info(hunk):
#     pass

# if __name__ == "__main__":
#     active_bug_path = "/home/user/data/d4j_wdirs/checkstyle/framework/projects/Checkstyle/active-bugs.csv"
#     project_layout_path = "/home/user/data/d4j_wdirs/checkstyle/framework/projects/Checkstyle/dir-layout.csv"
#     mine_results_dump_path = "/home/user/data/d4j_wdirs/checkstyle/mine_results/"
#     mine_diffs_dump_path = "/home/user/data/d4j_wdirs/checkstyle/mine_diffs/"
#     bug_candidates = read_csv_as_dict_list(active_bug_path)[:300][::-1]
#     project_layouts = read_flat_csv_as_dict(project_layout_path, key_index=0)
#     # ipdb.set_trace()
#     mine_project_bugs(project_id='checkstyle',
#                       bug_candidates=bug_candidates,
#                       project_layouts=project_layouts,
#                       mining_result_dump_base_path=mine_results_dump_path,
#                       mining_diff_dump_base_path=mine_diffs_dump_path,
#                       overwrite=False)

if __name__ == "__main__":
    import fire
    fire.Fire(parse_diff_size)