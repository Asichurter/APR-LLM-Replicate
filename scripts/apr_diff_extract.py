from typing import List, Tuple

from tree_sitter import Language, Parser
from tree_sitter import Node as ASTNode
import unidiff
import Levenshtein

from apr_utils import load_text

_lib_path_lists = [
    # 'build/my-languages.so',
    # '../../build/my-languages.so',
    # '../../../build/my-languages.so',
    # '../build/my-languages.so'
    '/data1/zhijietang/temp/language-build/java.so',
    '/data2/zhijietang/libs/treesitter-java/java.so'
]
# Name for tree-sitter lib loading
lang = 'java'   # 'cpp'
# Type of function/method declaration
func_tgt_types = ['method_declaration', 'constructor_declaration']    # 'function_definition'
# Type of the main body of the function/method
func_body_type = 'block'    #   'compound_statement'

_lib_loaded = False
for lib_path in _lib_path_lists:
    try:
        LANGUAGE = Language(lib_path, lang)
        _lib_loaded = True
    except Exception:
        print(f'[TreeSitter] Lib not found at: {lib_path}, try another.')
assert _lib_loaded

parser = Parser()
parser.set_language(LANGUAGE)

def encode_bytes(cont):
    return cont.encode('utf-8')

def decode_bytes(bytes_):
    return bytes_.decode('utf-8')

def parse_tree(code_text):
    return parser.parse(encode_bytes(code_text))

def retrieve_func_defination_nodes(cur_node: ASTNode, hit_nodes: List) -> List:
    # Only retrieve the top func def node
    if cur_node.type in func_tgt_types:
        hit_nodes.append(cur_node)
        return hit_nodes
    else:
        for child in cur_node.children:
            hit_nodes = retrieve_func_defination_nodes(child, hit_nodes)
        return hit_nodes

def compare_align_funcs_based_on_signatures(a_func_nodes: List[ASTNode], b_func_nodes: List[ASTNode]) -> List[Tuple]:
    """
    Return: Tuple

        -   Aligned a function node
        -   Aligned b function node
        -   Relative edit distance for a
        -   Function signature of a
        -   Function signature of b
    """
    a_sig_to_index, b_sig_to_index = {}, {}
    a_sigs, b_sigs = [], []
    for func_nodes, sig_to_index, sig_list in zip([a_func_nodes, b_func_nodes], [a_sig_to_index, b_sig_to_index], [a_sigs, b_sigs]):
        for i, func_node in enumerate(func_nodes):
            func_sig_list = []
            for func_child_node in func_node.children:
                # Only exclude the main body of the function (namely "{}" part) to generate signature
                if func_child_node.type != func_body_type:
                    func_sig_list.append(decode_bytes(func_child_node.text))
            func_sig = ' '.join(func_sig_list)
            sig_to_index[func_sig] = i
            sig_list.append(func_sig)

    matched_func_def_node_pairs = []
    # Align funcs based on a funcs, since we only care about before-changed-funs
    for a_sig, a_index in a_sig_to_index.items():
        matched = False
        distances, dist_sigs = [], []
        for b_sig, b_index in b_sig_to_index.items():
            sig_distance = Levenshtein.distance(a_sig, b_sig)
            distances.append(sig_distance)
            dist_sigs.append(b_sig)
            if sig_distance == 0:
                matched = True
                matched_func_def_node_pairs.append((a_func_nodes[a_index], b_func_nodes[b_index], sig_distance / len(a_sig), a_sig, b_sig))
                break

        # No exactly match, try to find the closest one among b
        if not matched:
            if len(distances) > 0:
                min_distance = min(distances)
                min_distance_index = distances.index(min_distance)
                min_distance_sig = dist_sigs[min_distance_index]
                matched_func_def_node_pairs.append((a_func_nodes[a_index], b_func_nodes[min_distance_index], min_distance / len(a_sig), a_sig, min_distance_sig))
            # If no funcs remained after change (deletion), use None to replace the after-change func node
            else:
                matched_func_def_node_pairs.append((a_func_nodes[a_index], None, None, a_sig, None))

    return matched_func_def_node_pairs


def extract_changed_funcs_from_diff(diff: str, compare_direc: bool = True) -> Tuple[List, bool]:
    """
    This method extract changed function pairs from diff, by following steps:

    1. Split before & after change code from diff. Only process uni-file diffs.
    2. Parse before & after change code with tree_sitter.
    3. Retreieve all the top function-defination nodes from before & after change code tree.
    4. Align and match the func-def nodes of before & after change code by comparing the edit distance between function signatures.
    5. Compare the text of before & after change code to determine whether the function has changed

    Return:
        Function and signature tuples, ordered as:
        -   Before-change function (target)
        -   After-changed function (not fully reliable)
        -   Before-change function signature
        =   After-change function signature

    Note:
        This method aims at extracting changed functions, namely before-change functions, thus for some cases
        epspecially change of function signature, there may be a not-matched function signature has the minimum distance
        (such as function deletion). Therefore, this method can not accurately extract these after-change functions and
        ONLY BEFORE-CHANGED RETURNING IS FULLY RELIABLE.

        If after-change side function is preferred, set "compare_direc"=False.
    """
    patch_set = unidiff.PatchSet(diff)
    if len(patch_set) == 0:
        print(f"Warning: Get {len(patch_set)} changed files in the diff, do not extract [extract_changed_before_cpp_funcs_from_diff]")
        return [], False

    commit_changed_funcs = []
    for file in patch_set:
        if file.path == '.defects4j.config':
            continue
        # Separate add/remove lines from diff
        before_code, after_code = '', ''
        for hunk in file:
            for line in hunk:
                if line.is_context:
                    before_code += line.value
                    after_code += line.value
                elif compare_direc:
                    if line.is_added:
                        after_code += line.value[1:]  # Remove the "-" or "+" character at line head
                    if line.is_removed:
                        before_code += line.value[1:]
                else:
                    if line.is_removed:
                        after_code += line.value[1:]  # Remove the "-" or "+" character at line head
                    if line.is_added:
                        before_code += line.value[1:]

        # Extract funcs file-by-file
        before_tree = parser.parse(encode_bytes(before_code))
        after_tree = parser.parse(encode_bytes(after_code))
        before_func_nodes = retrieve_func_defination_nodes(before_tree.root_node, [])
        after_func_nodes = retrieve_func_defination_nodes(after_tree.root_node, [])

        aligned_func_nodes = compare_align_funcs_based_on_signatures(before_func_nodes, after_func_nodes)
        changed_func_nodes = []
        for before_node, after_node, dist_ratio, a_sig, b_sig in aligned_func_nodes:
            if after_node is None:
                changed_func_nodes.append(before_node)
            # Signature matched & Func changed
            elif dist_ratio == 0:
                if before_node.text != after_node.text:
                    changed_func_nodes.append(before_node)
            # Two cases:
            # 1. Func deleted, no matched b func
            # 2. Func signature changed
            # (Both two cases belong to "before-fun changed")
            else:
                changed_func_nodes.append(before_node)

        commit_changed_funcs.append({
            'file': file,
            'changed_funcs': changed_func_nodes
        })

    return commit_changed_funcs, True


if __name__ == '__main__':
    # diff_path = '/data1/zhijietang/vul_data/datasets/treevul-CVE/changed_funcs/treevul_filtered_diffs_v2/diffs/abrt---abrt---6e811d78e2719988ae291181f5b133af32ce62d8.diff'
    # diff_path = '/data1/zhijietang/vul_data/datasets/treevul-CVE/changed_funcs/treevul_filtered_diffs_v2/diffs/aawc---unrar---0ff832d31470471803b175cfff4e40c1b08ee779.diff'
    # diff_path = '/data1/zhijietang/vul_data/datasets/treevul-CVE/changed_funcs/treevul_filtered_diffs_v2/diffs/abrt---abrt---4f2c1ddd3e3b81d2d5146b883115371f1cada9f9.diff'
    diff_path = '/data2/zhijietang/projects/libro/data/apr_wdir/diff/d4j_Csv_10.diff'
    diff = load_text(diff_path)
    changed_files, ok = extract_changed_funcs_from_diff(diff)
    #
    # prompts = []
    # for changed_file in changed_files:
    #     file_changed_func_prompts = build_infill_prompt_for_funcs(changed_file['file'], changed_file['changed_funcs'], '<INFILL>')
    #     prompts.append({
    #         'file_path': changed_file['file'].path,
    #         'func_infill_prompts': file_changed_func_prompts
    #     })
    #
    # from utils.file import read_dumped
    # datas = read_dumped("/data2/zhijietang/vul_data/datasets/joern_vulberta/packed_hybrid_vol_1.pkl")
    # tree = parser.parse(encode_bytes())
