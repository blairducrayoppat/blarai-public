import openvino as ov
core = ov.Core()
device = "NPU"
for prop in ["NPU_COMPILER_VERSION", "NPU_DRIVER_VERSION", "NPU_COMPILER_TYPE"]:
    try:
        val = core.get_property(device, prop)
        print(f"{prop}: {val}")
    except Exception as e:
        print(f"{prop}: ERROR - {e}")

# Also check pip versions
import subprocess, sys
result = subprocess.run([sys.executable, "-m", "pip", "list"], capture_output=True, text=True)
for line in result.stdout.splitlines():
    if any(k in line.lower() for k in ["openvino", "optimum", "nncf"]):
        print(f"  PIP: {line.strip()}")
