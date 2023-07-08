from typing import List, Dict
import logging
import os
import traceback

from apr_utils import read_csv_as_dict_list, git_export_diff, dump_json, \
                      read_flat_csv_as_dict, git_get_commit_data
from apr_stat_utils import parse_diff_size
from apr_reproduce_bug import twover_run_experiment
from apr_config import bug_mining_config


DEBUG = False

if DEBUG:
    pass

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
    time_since = bug_mining_config[project_id]["time_since"]
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

        try:
            postfix_date = git_get_commit_data(repo_path, postfix_commit)
            if postfix_date < time_since:
                logger.warning(f"Skip #{i}: {prefix_commit} - {postfix_commit}, due to time filter: {postfix_date} < {time_since}")
                continue
            # Get src & test dir
            prefix_src_path, prefix_test_path = project_layouts[prefix_commit]
            postfix_src_path, postfix_test_path = project_layouts[postfix_commit]
        except KeyError:
            prefix_src_path, prefix_test_path = default_src_dir, default_test_dir
            postfix_src_path, postfix_test_path = default_src_dir, default_test_dir
        except RuntimeError as e:
            logger.error(f"Error when init #{i} {prefix_commit} - {postfix_commit}: {e}. Skipped")
            continue

        try:
            logger.info("\n\n" + "#"*75 + f"\nChecking {project_id} #{i}: {prefix_commit} - {postfix_commit} ({postfix_date}) ...\n" + "#"*75)
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
            reproduction_result = twover_run_experiment(repo_path, prefix_commit, postfix_commit, project_id,
                                                        prefix_test_path,
                                                        **twoover_extra_args)
            logger.info("Parsing diff size ...")
            size_result = parse_diff_size(diff_path)
            final_result = {
                "project": project_id,
                "info": {
                    "index": i,
                    "prefix_commit": prefix_commit,
                    "postfix_commit": postfix_commit,
                    "postfix_commit_date": postfix_date,
                    "issue_id": bug["report.id"],
                    "issue_url": bug["report.url"],
                },
                "size": size_result,
                "reproduction": reproduction_result,
            }
            logger.info(f"Dumping {project_id} #{i} to {bug_result_dump_path} ...")
            dump_json(final_result, bug_result_dump_path)

            # return

        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error for {project_id} #{i}: {prefix_commit} - {postfix_commit}: {e}")

        # # todo: remove
        # if i == 10:
        #     return


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

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--project', default='checkstyle')
    parser.add_argument('--debug', action="store_true", default=False)
    parser.add_argument('--overwrite', action="store_true", default=False)
    args = parser.parse_args()

    DEBUG = args.debug

    active_bug_path = "/home/user/data/d4j_wdirs/checkstyle/framework/projects/Checkstyle/active-bugs.csv"
    project_layout_path = "/home/user/data/d4j_wdirs/checkstyle/framework/projects/Checkstyle/dir-layout.csv"
    mine_results_dump_path = "/home/user/data/d4j_wdirs/checkstyle/mine_results/"
    mine_diffs_dump_path = "/home/user/data/d4j_wdirs/checkstyle/mine_diffs/"
    bug_candidates = read_csv_as_dict_list(active_bug_path)[::-1]
    project_layouts = read_flat_csv_as_dict(project_layout_path, key_index=0)
    # ipdb.set_trace()
    mine_project_bugs(project_id=args.project,
                      bug_candidates=bug_candidates,
                      project_layouts=project_layouts,
                      mining_result_dump_base_path=mine_results_dump_path,
                      mining_diff_dump_base_path=mine_diffs_dump_path,
                      overwrite=args.overwrite)

# if __name__ == "__main__":
#     import fire
#     fire.Fire(parse_diff_size)