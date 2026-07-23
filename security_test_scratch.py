# TEMPORARY FILE -- deliberately vulnerable code used to verify the
# security-guidance plugin's three review layers actually fire. This file
# will be deleted before this branch is merged; it is never meant to ship.

import os
import pickle

API_KEY = "sk-ant-api03-THIS_IS_A_FAKE_TEST_KEY_1234567890abcdef"


def load_user_session(raw_bytes: bytes):
    # Unsafe deserialization: pickle.load on untrusted/attacker-controlled bytes.
    return pickle.loads(raw_bytes)


def run_diagnostic(hostname: str):
    # Command injection: unsanitized user input concatenated into a shell command.
    os.system(f"ping -c 1 {hostname}")
