from typing import Dict, List
import traceback
import unidiff

from apr_diff_extract import extract_changed_funcs_from_diff
from apr_utils import load_text
from apr_log import get_logger

def parse_diff_size(diff_path,
                    test_prefix: str = 'src/test/java',
                    src_prefix: str = 'src/main/java',
                    t_logger = None):
    t_logger = t_logger or get_logger(__name__)
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
        try:
            f_changed_funcs, ok = extract_changed_funcs_from_diff(str(file), sig_only=True)
        except RecursionError as e:
            traceback.print_exc()
            t_logger.error(f"Recursion error when extracting changed funcs: {e}")
            f_changed_funcs, ok = None, False

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