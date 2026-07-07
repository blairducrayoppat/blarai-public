import subprocess, sys, importlib

# Check transformers version
try:
    import transformers
    print(f"transformers: {transformers.__version__}")
except ImportError:
    print("transformers: NOT INSTALLED")

# Check NPU driver via Windows
result = subprocess.run(
    ["powershell", "-Command",
     "Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DeviceName -like '*NPU*' -or $_.DeviceName -like '*AI Boost*' -or $_.DeviceName -like '*Neural*' } | Select-Object DeviceName, DriverVersion, DriverDate | Format-List"],
    capture_output=True, text=True, timeout=30
)
print("\n--- NPU Driver (Windows) ---")
print(result.stdout.strip() if result.stdout.strip() else "No NPU driver found via WMI")

# Also check via Device Manager style query
result2 = subprocess.run(
    ["powershell", "-Command",
     "Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.InfName -like '*npu*' -or $_.HardwareID -like '*VPU*' -or $_.HardwareID -like '*7D1D*' } | Select-Object DeviceName, DriverVersion, InfName | Format-List"],
    capture_output=True, text=True, timeout=30
)
print("\n--- NPU Driver (by HardwareID) ---")
print(result2.stdout.strip() if result2.stdout.strip() else "No match")

# Check OpenVINO's reported driver
import openvino as ov
core = ov.Core()
drv = core.get_property("NPU", "NPU_DRIVER_VERSION")
print(f"\nOpenVINO NPU_DRIVER_VERSION: {drv}")

# Decode the driver version integer
# Intel driver versions are typically in format: major.minor.build.revision
# The integer 1004514 might decode differently
print(f"Raw integer: {drv}")

# Check for latest NPU driver recommendation
print(f"\nDocs recommend: NPU driver >= 32.0.100.3104")
print(f"Docs recommend: transformers==4.51.3 for NPU export (OV 2026.0)")
print(f"Docs recommend: optimum-intel==1.25.2 for NPU export (OV 2026.0)")
print(f"Docs recommend: nncf==2.18.0 for NPU export (OV 2026.0)")
