import re

failed_file_pattern = re.compile("\[ERROR\] Tests run: [0-9]*, Failures: [0-9]*, Errors: [0-9]*, Skipped: [0-9]*, Time elapsed: .* s <<< FAILURE! - in ([a-zA-Z.]*)")
failure_method_pattern = re.compile("\[ERROR\] ([a-zA-Z]*)  Time elapsed: [0-9\.]* s  <<< FAILURE\!")
error_method_pattern = re.compile("\[ERROR\] ([a-zA-Z]*)  Time elapsed: [0-9\.]* s  <<< ERROR\!")

def extract_failed_file(line: str):
    return re.findall(failed_file_pattern, line)

def extract_failure_method(line: str):
    return re.findall(failure_method_pattern, line)

def extract_error_method(line: str):
    return re.findall(error_method_pattern, line)

if __name__ == "__main__":
    line = "[ERROR] testInlineForbidden  Time elapsed: 0.045 s  <<< FAILURE!"
    print(extract_failure_method(line))