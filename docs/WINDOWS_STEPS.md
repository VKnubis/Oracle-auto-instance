# Windows Steps

This runs from your PC and controls Oracle Cloud through the OCI API.

## 1. Setup Python packages

Double-click:

```text
run_once_windows.bat
```

It will run setup automatically if `.venv` is missing.

## 2. Fill `.env`

Copy `config/config.example.env` to `.env`, then open `.env` in Notepad and fill:

```text
OCI_COMPARTMENT_ID=...
OCI_SUBNET_ID=...
OCI_IMAGE_ID=
OCI_IMAGE_OS=Oracle Linux
OCI_IMAGE_OS_VERSION=
OCI_AVAILABILITY_DOMAIN=...
OCI_SHAPE=VM.Standard.A1.Flex
OCI_OCPUS=1
OCI_MEMORY_GB=6
DELETE_FAILED_INSTANCE=true
INSTANCE_WAIT_SECONDS=900
CAPACITY_RETRY_SUCCESS_EXIT=true
```

## 3. Add Oracle API key

You need an OCI config file here:

```text
C:\Users\<your user>\.oci\config
```

And the matching public API key must be added in Oracle Console:

```text
Profile icon -> My profile -> API keys -> Add API key
```

## 4. Test once

First check the Oracle API config:

```text
check_oci_config.bat
```

Double-click:

```text
run_once_windows.bat
```

Temporary E2 Micro test:

```text
run_e2micro_test.bat
```

## 5. Start automatic mode

Double-click:

```text
start_auto_windows.bat
```

## 6. Stop automatic mode

Double-click:

```text
stop_auto_windows.bat
```

Your PC must stay awake. If Windows sleeps, the automation stops until it wakes.
