# `aiida-charmm-gui`
[![Build Status](https://github.com/ovcarj/aiida-charmm-gui/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ovcarj/aiida-charmm-gui/actions)

AiiDA plugin for submitting jobs to the [CHARMM-GUI](https://charmm-gui.org) REST-like API, polling their status, and storing results in the AiiDA provenance graph.

## Table of contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Installation](#installation)
- [Authentication](#authentication)
- [Usage](#usage)
  - [Running the WorkChain](#running-the-workchain)
  - [Example: Quick Bilayer membrane](#example-quick-bilayer-membrane)
  - [Retrieving results](#retrieving-results)
- [WorkChain inputs and outputs](#workchain-inputs-and-outputs)
- [Proactive token refresh](#proactive-token-refresh)
- [Development](#development)

---

## Overview

The typical job lifecycle managed by this plugin is:

1. **Login** — `aiida-charmm-gui login` authenticates with CHARMM-GUI and caches a JWT token locally. This step is intentionally outside AiiDA provenance.
2. **Submit** — POST parameters to a module endpoint (e.g. `/api/quick_bilayer`), receive a `jobid`.
3. **Poll** — GET `/api/check_status?jobid=<ID>` until the status is `"done"` or an error.
4. **Download** — GET `/api/download?jobid=<ID>`, unpack the `.tgz` archive into a `FolderData` node.

Steps 2–4 are orchestrated by `CharmmGuiWorkChain` and captured in the AiiDA provenance graph.

---

## Requirements

- Python ≥ 3.9
- [AiiDA](https://aiida.net) ≥ 2.5 (with a configured profile and running daemon)
- A CHARMM-GUI account with REST API access

---

## Installation

```bash
git clone https://github.com/ovcarj/aiida-charmm-gui
cd aiida-charmm-gui
pip install -e .
```

If you have not set up an AiiDA profile yet, run:

```bash
verdi quicksetup
verdi daemon start
```

---

## Authentication

Before submitting any jobs you must log in to cache a token locally. The token is valid for 36 hours.

**Interactive login:**

```bash
aiida-charmm-gui login --username your@email.com --password yourpassword
```

**Using environment variables (not recommended):**

```bash
export CHARMM_GUI_USER=your@email.com
export CHARMM_GUI_PASS=yourpassword
aiida-charmm-gui login
```

**Check whether a valid token is cached:**

```bash
aiida-charmm-gui login --status
# exits 0 if valid, 1 if missing or expired
```

The token is written to `~/.cache/aiida-charmm-gui/token.json`. Pass a custom path via `--token-file` if needed.

---

## Usage

### Running the WorkChain

Load the WorkChain by its entry point and submit it with the `submit` helper:

```python
from aiida import load_profile, orm
from aiida.engine import submit

load_profile()

WorkChain = WorkflowFactory("charmm_gui.base")

inputs = {
    "submission_url": orm.Str("https://charmm-gui.org/api/<module>"),
    "parameters": orm.Dict({"param1": "value1", "param2": "value2"}),
    # optional:
    "poll_interval": orm.Int(60),      # seconds between status checks (default 30)
    "download_timeout": orm.Int(900),  # seconds to wait for archive (default 600)
}

node = submit(WorkChain, **inputs)
print(f"Submitted WorkChain pk={node.pk}")
```

Monitor progress:

```bash
verdi process list -a
verdi process show <pk>
verdi process report <pk>   # detailed step-by-step log
```

---

### Example: Quick Bilayer membrane

The following example builds a simple DPPC lipid bilayer using the CHARMM-GUI Quick Bilayer module. The `parameters` dictionary corresponds to the form fields accepted by the `/api/quick_bilayer` endpoint.

```python
from aiida import load_profile, orm
from aiida.engine import submit
from aiida.plugins import WorkflowFactory

load_profile()

WorkChain = WorkflowFactory("charmm_gui.base")

# Parameters for a symmetric DPPC bilayer with ~72 lipids per leaflet
bilayer_parameters = {
    # Lipid composition — upper leaflet
    "lipid1_upper": "DPPC",
    "num1_upper": "36",
    # Lipid composition — lower leaflet (symmetric)
    "lipid1_lower": "DPPC",
    "num1_lower": "36",
    # Water and ion options
    "waterz": "17.5",       # water layer thickness in Å
    "salt_conc": "0.15",    # KCl concentration in mol/L
    "cation": "K",
    "anion": "CL",
    # Force field
    "ff": "charmm36",
}

inputs = {
    "submission_url": orm.Str("https://charmm-gui.org/api/quick_bilayer"),
    "parameters": orm.Dict(bilayer_parameters),
    "poll_interval": orm.Int(60),
    "download_timeout": orm.Int(900),
}

node = submit(WorkChain, **inputs)
print(f"WorkChain submitted: pk={node.pk}, uuid={node.uuid}")
```

Track the job:

```bash
verdi process list -a
verdi process report <pk>
```

A successful run produces output similar to:

```
[submit_job]     Submitted job 1234567890 (modules: quick_bilayer).
[check_job_status] Job 1234567890 status: running quick_bilayer.
[check_job_status] Job 1234567890 status: running quick_bilayer.
[check_job_status] Job 1234567890 status: done.
[download_results] Results stored for job 1234567890.
```

---

### Retrieving results

Once the WorkChain finishes, two outputs are available:

```python
from aiida import load_profile, orm

load_profile()

node = orm.load_node(<pk>)

# The CHARMM-GUI job identifier
jobid = node.outputs.jobid.value
print(f"Job ID: {jobid}")

# The unpacked archive as a FolderData node
results = node.outputs.results
print("Files in results:")
for name in results.list_object_names():
    print(f"  {name}")
```

To export the results to a local directory:

```python
import shutil

results.copy_tree("/path/to/output/directory")
```

---

## WorkChain inputs and outputs

### Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `submission_url` | `Str` | yes | — | Full URL of the module endpoint, e.g. `https://charmm-gui.org/api/quick_bilayer` |
| `parameters` | `Dict` | yes | — | Form fields sent as POST body |
| `token_file` | `Str` | no | `~/.cache/aiida-charmm-gui/token.json` | Path to the cached token written by `aiida-charmm-gui login` |
| `poll_interval` | `Int` | no | `30` | Seconds between status-check requests |
| `download_timeout` | `Int` | no | `600` | Maximum seconds to wait for the archive to be packaged after the job reports `done` |

### Outputs

| Name | Type | Description |
|---|---|---|
| `jobid` | `Str` | CHARMM-GUI job identifier |
| `results` | `FolderData` | Unpacked contents of the `.tgz` archive |

### Exit codes

| Code | Label | Meaning |
|---|---|---|
| 300 | `ERROR_SUBMISSION_FAILED` | The POST request failed or the server did not confirm submission |
| 301 | `ERROR_JOB_FAILED` | The remote job finished with an error status |
| 302 | `ERROR_DOWNLOAD_FAILED` | The archive could not be downloaded within `download_timeout` |

---

## Proactive token refresh

For long-running WorkChains, `CharmmGuiClient` will silently obtain a fresh token if the cached one expires within one hour — provided `CHARMM_GUI_USER` and `CHARMM_GUI_PASS` are set in the environment of the AiiDA daemon. If the refresh attempt fails, the still-valid cached token is used as a fallback.

To make the daemon aware of the credentials, set the variables before starting it:

```bash
export CHARMM_GUI_USER=your@email.com
export CHARMM_GUI_PASS=yourpassword
verdi daemon start
```

---

## Development

Install development dependencies and set up the pre-commit hook:

```bash
pip install -e ".[pre-commit]"
pre-commit install
```

Run the test suite:

```bash
hatch test                          # current Python version
hatch test --python 3.11            # specific version
hatch test --coverage               # with coverage report
hatch test -- tests/test_client.py  # single file
```

Check and fix code style (ruff, line-length 120):

```bash
hatch fmt --check
hatch fmt
```

Build the package:

```bash
hatch build
```
