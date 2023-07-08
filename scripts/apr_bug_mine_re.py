import re

failed_file_pattern = re.compile("\[ERROR\] Tests run: [0-9]*, Failures: [0-9]*, Errors: [0-9]*, Skipped: [0-9]*, Time elapsed: .* s <<< FAILURE! - in ([a-zA-Z.]*)")
failure_method_pattern = re.compile("\[ERROR\] ([a-zA-Z]*)  Time elapsed: [0-9\.]* s  <<< FAILURE\!")
error_method_pattern = re.compile("\[ERROR\] ([a-zA-Z]*)  Time elapsed: [0-9\.]* s  <<< ERROR\!")