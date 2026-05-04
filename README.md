# Oracle Auto Instance

Windows-friendly Oracle Cloud bot that retries creating a compute instance every 5-15 minutes. It was made for `VM.Standard.A1.Flex` capacity hunting, but it also includes a temporary `VM.Standard.E2.1.Micro` test runner.

The bot uses Oracle's official Python SDK. It does not use Cloud Shell or browser automation.

## What It Does

- Launches OCI compute instances from your PC.
- Auto-picks the newest compatible Oracle Linux image when `OCI_IMAGE_ID` is blank.
- Injects your SSH public key into new instances.
- Treats `Out of host capacity` as a normal retry case.
- Waits for a launched instance to become `RUNNING`.
- Terminates an instance if OCI reports it failed before reaching `RUNNING`.
- Can run in the background with Windows Task Scheduler.

## Quick Start On Windows

1. Install Python 3.
2. Copy `config/config.example.env` to `.env`.
3. Fill `.env` with your OCI values.
4. Create an OCI API key/config at:

```text
C:\Users\<you>\.oci\config
```

5. Check the Oracle API login:

```text
check_oci_config.bat
```

6. Test one launch:

```text
run_once_windows.bat
```

7. Start automatic retries:

```text
start_auto_windows.bat
```

8. Stop automatic retries:

```text
stop_auto_windows.bat
```

Your PC must stay awake for the scheduled task to keep running.

## Required `.env` Values

```text
OCI_COMPARTMENT_ID=ocid1.compartment.oc1..your_value
OCI_SUBNET_ID=ocid1.subnet.oc1..your_value
OCI_IMAGE_ID=
OCI_IMAGE_OS=Oracle Linux
OCI_IMAGE_OS_VERSION=
OCI_AVAILABILITY_DOMAIN=your_ad

OCI_SHAPE=VM.Standard.A1.Flex
OCI_OCPUS=1
OCI_MEMORY_GB=6

OCI_CONFIG_FILE=C:\Users\<you>\.oci\config
OCI_PROFILE=DEFAULT

INSTANCE_NAME_PREFIX=auto-instance
ASSIGN_PUBLIC_IP=true
SSH_PUBLIC_KEY=ssh-ed25519 or ssh-rsa public key here

DELETE_FAILED_INSTANCE=true
INSTANCE_WAIT_SECONDS=900
CAPACITY_RETRY_SUCCESS_EXIT=true
```

Leave `OCI_IMAGE_ID` blank unless you want to force a specific image OCID.

## E2 Micro Test

Use this to confirm your API key, subnet, compartment, and SSH key work before running A1.Flex retries.

1. Copy:

```text
config/e2micro.example.env
```

to:

```text
config/.env.e2micro
```

2. Fill the values.
3. Run:

```text
run_e2micro_test.bat
```

## Project Layout

```text
loop.py                         Main OCI launcher
requirements.txt                Python dependencies
run_once_windows.bat            Run one A1.Flex attempt
start_auto_windows.bat          Register Windows scheduled retry task
stop_auto_windows.bat           Remove Windows scheduled retry task
check_oci_config.bat            Test OCI API config
run_e2micro_test.bat            Run one E2 Micro test
config/                         Example env files
scripts/windows/                Windows helper scripts
scripts/tests/                  Test launch helpers
deploy/linux/                   Optional Linux installer
deploy/systemd/                 Optional systemd units
docs/                           Extra notes
```

## Optional Linux Install

```bash
sudo bash deploy/linux/install_ubuntu.sh
sudo nano /etc/loop-oracle.env
sudo systemctl start loop-oracle.timer
```

## Safety

This can create paid cloud resources. Watch your OCI limits, billing, and running instances. Keep `.env`, OCI private keys, and SSH private keys out of GitHub.
