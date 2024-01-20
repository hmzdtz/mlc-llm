# pylint: disable=missing-docstring
import concurrent.futures as cf
import os
import shlex
import subprocess
import sys
import tempfile
from itertools import product

import tvm

from mlc_chat.model import MODEL_PRESETS
from mlc_chat.support.constants import MLC_TEMP_DIR

OPT_LEVEL = "O2"
DEVICE2TARGET = {
    "cuda": tvm.target.Target(
        {
            "kind": "cuda",
            "arch": "sm_86",
            "max_threads_per_block": 1024,
            "max_num_threads": 1024,
            "max_shared_memory_per_block": 49152,
            "thread_warp_size": 32,
        }
    ),
    "rocm": tvm.target.Target(
        {
            "kind": "rocm",
            "mtriple": "amdgcn-amd-amdhsa-hcc",
            "mcpu": "gfx1100",
            "thread_warp_size": 32,
            "max_threads_per_block": 1024,
            "max_num_threads": 256,
            "max_shared_memory_per_block": 65536,
        }
    ),
    "vulkan": tvm.target.Target(
        {
            "kind": "vulkan",
            "max_threads_per_block": 1024,
            "max_num_threads": 256,
            "max_shared_memory_per_block": 32768,
            "thread_warp_size": 1,
            "supports_int16": 1,
            "supports_float32": 1,
            "supports_int32": 1,
            "supports_int8": 1,
            "supports_16bit_buffer": 1,
            "supports_float16": 1,
        }
    ),
}
DEVICE2SUFFIX = {
    "cuda": "so",
    "rocm": "so",
    "vulkan": "so",
}
MODELS = list(MODEL_PRESETS.keys())
QUANTS = list(mlc_chat.quantization.QUANTIZATION.keys())
TENSOR_PARALLEL_SHARDS = [
    1,
]


def run_command(log_file, cmd):
    with open(log_file, "w", encoding="utf-8") as file:
        subprocess.check_call(
            cmd,
            stdout=file,
            stderr=subprocess.STDOUT,
        )


def test_model_compile():  # pylint: disable=too-many-locals
    device = sys.argv[1]
    num_workers = int(sys.argv[2])
    target = str(DEVICE2TARGET[device])
    suffix = DEVICE2SUFFIX[device]

    passed_cmds = []
    failed_cmds = []
    with tempfile.TemporaryDirectory(dir=MLC_TEMP_DIR) as tmp_dir:
        with cf.ProcessPoolExecutor(max_workers=num_workers) as executor:
            log_files = []
            cmds = []
            futures = []
            for idx, (model, quant, tp_shard) in enumerate(
                product(
                    MODELS,
                    QUANTS,
                    TENSOR_PARALLEL_SHARDS,
                )
            ):
                log_file = os.path.join(tmp_dir, f"lib{idx}.log")
                cmd = [
                    sys.executable,
                    "-m",
                    "mlc_chat",
                    "compile",
                    model,
                    "--quantization",
                    quant,
                    "--overrides",
                    f"tensor_parallel_shards={tp_shard}",
                    "--device",
                    target,
                    "--opt",
                    OPT_LEVEL,
                    "-o",
                    os.path.join(tmp_dir, f"lib{idx}.{suffix}"),
                ]
                future = executor.submit(run_command, log_file, cmd)
                log_files.append(log_file)
                cmds.append(cmd)
                futures.append(future)
            for log_file, cmd, future in zip(log_files, cmds, futures):
                cmd = shlex.join(cmd)
                try:
                    future.result()
                    passed_cmds.append(cmd)
                    print(f"[PASS] {cmd}")
                except Exception:  # pylint: disable=broad-except
                    failed_cmds.append(cmd)
                    print("-------------------------------")
                    print(f"[FAIL] {cmd}")
                    with open(log_file, "r", encoding="utf-8") as file:
                        print(file.read())
                    print("-------------------------------")
    print("-------------------------------")
    print(f"Total {len(passed_cmds)} passed, {len(failed_cmds)} failed.")
    print("-------------------------------")
    print("Passed commands:")
    for cmd in passed_cmds:
        print(cmd)
    if failed_cmds:
        print("-------------------------------")
        print("Failed commands:")
        for cmd in failed_cmds:
            print(cmd)
        sys.exit(1)


if __name__ == "__main__":
    test_model_compile()
