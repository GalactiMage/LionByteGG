import json
import os
import tempfile


def safe_json_dump(data, filepath, **kwargs):
    """
    Atomically write JSON data to a file.
    Writes to a temp file first, then uses os.replace() to swap it in.
    This prevents data corruption if the process crashes mid-write.
    """
    kwargs.setdefault("ensure_ascii", False)
    dirpath = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(dirpath, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=dirpath, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, **kwargs)
        os.replace(temp_path, filepath)
    except BaseException:
        # Clean up the temp file if anything goes wrong
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
