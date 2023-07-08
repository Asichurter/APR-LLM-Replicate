

reproduce_config = {
    'checkstyle': {
        'repo_path': '/home/user/projects/checkstyle/',
        'src_dir': 'src/main/java/',
        'test_prefix': 'src/test/java/',
        'project_name': 'checkstyle',
        'project_id': 'checkstyle',
        'timeout': '10m',
        'extra_test_config': []
    }
}

bug_mining_config = {
    'checkstyle': {
        "repo_path": "/home/user/projects/checkstyle/",
        "time_since": "2021-04",
        "size_limit": {
            "not_test_file": 1,
            "not_test_hunk": 3,
            "not_test_func": 3,
            "not_test_loc": 30,
        },
        "reproduction": {
            "pre_fix_ver": {
                "run_succeed": True,
                "test_passed": None     # None refer to "not limit"
            },
            "post_fix_ver": {
                "run_succeed": True,
                "test_passed": True
            },
            'timeout': '30m',
            'extra_test_config': []
        }
    }
}