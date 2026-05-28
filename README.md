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
  - [Example: Quick Bilayer with typed inputs](#example-quick-bilayer-with-typed-inputs)
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

The following example builds a mixed DOPC/POPC/cholesterol bilayer using the CHARMM-GUI Quick Bilayer module. Lipid compositions are passed as a single colon-separated string `"LIPID1:LIPID2:...=ratio1:ratio2:..."`. The `membrane_only` flag skips adding water/ions (useful for a dry-run or when you want to add solvent yourself), and `margin` sets the XY box margin in Å.

```python
from aiida import load_profile, orm
from aiida.engine import submit
from aiida.plugins import WorkflowFactory

load_profile()

WorkChain = WorkflowFactory("charmm_gui.base")

bilayer_parameters = {
    # Upper leaflet: DOPC:POPC:cholesterol in 1:1:2 ratio
    "upper": "DOPC:POPC:CHL1=1:1:2",
    # Lower leaflet: DOPC:POPC:cholesterol in 1:2:1 ratio
    "lower": "DOPC:POPC:CHL1=1:2:1",
    # Build without protein (no jobid_pdb required)
    "membrane_only": "true",
    # XY box margin in Å
    "margin": "20",
}

inputs = {
    "submission_url": orm.Str("https://charmm-gui.org/api/quick_bilayer"),
    "parameters": orm.Dict(bilayer_parameters),
    # token_file and poll_interval use their defaults
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

### Example: Quick Bilayer with typed inputs

`QuickBilayerWorkChain` (`charmm_gui.quick_bilayer`) wraps the generic chain and exposes each Quick Bilayer parameter as a typed AiiDA input. The same bilayer as above, but without constructing a raw parameters dict:

```python
from aiida import load_profile, orm
from aiida.engine import submit
from aiida.plugins import WorkflowFactory

load_profile()

QuickBilayerWorkChain = WorkflowFactory("charmm_gui.quick_bilayer")

node = submit(
    QuickBilayerWorkChain,
    upper=orm.Str("DOPC:POPC:CHL1=1:1:2"),
    lower=orm.Str("DOPC:POPC:CHL1=1:2:1"),
    membrane_only=orm.Bool(True),
    margin=orm.Float(20.0),
    # poll_interval, download_timeout, token_file use their defaults
)
print(f"WorkChain submitted: pk={node.pk}, uuid={node.uuid}")
```

Invalid parameter combinations (e.g. providing both `upper`/`lower` and `membtype`, or omitting `jobid_pdb` for a protein system) are caught in a `validate_inputs` step before anything is sent to CHARMM-GUI, so failures are immediate and clearly reported.

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

### `CharmmGuiWorkChain` (`charmm_gui.base`)

#### Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `submission_url` | `Str` | yes | — | Full URL of the module endpoint, e.g. `https://charmm-gui.org/api/quick_bilayer` |
| `parameters` | `Dict` | yes | — | Form fields sent as POST body |
| `token_file` | `str` (non-db) | no | `~/.cache/aiida-charmm-gui/token.json` | Path to the cached token written by `aiida-charmm-gui login`. Not stored in the provenance graph. |
| `poll_interval` | `Int` | no | `30` | Seconds between status-check requests |
| `download_timeout` | `Int` | no | `600` | Maximum seconds to wait for the archive to be packaged after the job reports `done` |

#### Outputs

| Name | Type | Description |
|---|---|---|
| `jobid` | `Str` | CHARMM-GUI job identifier |
| `results` | `FolderData` | Unpacked contents of the `.tgz` archive |

#### Exit codes

| Code | Label | Meaning |
|---|---|---|
| 300 | `ERROR_SUBMISSION_FAILED` | The POST request failed or the server did not confirm submission |
| 301 | `ERROR_JOB_FAILED` | The remote job finished with an error status |
| 302 | `ERROR_DOWNLOAD_FAILED` | The archive could not be downloaded within `download_timeout` |

---

### `QuickBilayerWorkChain` (`charmm_gui.quick_bilayer`)

#### Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `upper` | `Str` | see note | — | Upper leaflet lipid composition, e.g. `"DOPC:POPC:CHL1=1:1:2"`. Required unless `membtype` is set. |
| `lower` | `Str` | see note | — | Lower leaflet lipid composition. Required unless `membtype` is set. |
| `membtype` | `Str` | see note | — | Preset membrane type (e.g. `"PMm"`, `"PMf"`). Required unless `upper`/`lower` are set. |
| `jobid_pdb` | `Str` | see note | — | Job ID from the PDB Reader module. Required unless `membrane_only` is `True`. |
| `membrane_only` | `Bool` | no | `False` | Build a lipid-only system without protein. |
| `margin` | `Float` | yes | — | Box boundary margin in Å. |
| `wdist` | `Float` | no | `22.5` | Z-length water boundary in Å. |
| `ion_conc` | `Float` | no | `0.15` | Ion concentration in M. |
| `ion_type` | `Str` | no | `"NaCl"` | Ion type, e.g. `"NaCl"` or `"KCl"`. |
| `prot_projection_upper` | `Bool` | no | `False` | Enable protein projection on upper leaflet. |
| `prot_projection_lower` | `Bool` | no | `False` | Enable protein projection on lower leaflet. |
| `ppm` | `Bool` | no | `False` | Enable PPM support. |
| `topology_in` | `Bool` | no | `True` | Include N-terminal. |
| `heteroatoms` | `Bool` | no | `False` | Include hetero atoms. |
| `clone_job` | `Bool` | no | `False` | Copy job directory for multiple lipid compositions. |
| `run_ff_converter` | `Bool` | no | `True` | Run the CHARMM-GUI force-field converter to produce GROMACS, AMBER, NAMD, and OpenMM input files in addition to the default CHARMM outputs (API field: `run_ffconverter`). |
| `temperature` | `Float` | no | `303.15` | Simulation temperature in K, used by the force-field converter when generating MD input files. |
| `align_option` | `Int` | no | `1` | Protein alignment option (API field: `align_option`). |
| `hetero_xy_option` | `Str` | no | `"margin"` | How to determine XY box size for hetero atoms (API field: `hetero_xy_option`). |
| `charmmff_wyf_checked` | `Bool` | no | `False` | Enable CHARMM WYF force-field option (API field: `charmmff_wyf_checked`). |
| `charmmff_hmr_checked` | `Bool` | no | `True` | Enable hydrogen mass repartitioning (API field: `charmmff_hmr_checked`). |
| `charmm_mini` | `Bool` | no | `False` | Run CHARMM minimization step (API field: `charmm_mini`). |
| `token_file` | `str` (non-db) | no | `~/.cache/aiida-charmm-gui/token.json` | Path to the cached token. Not stored in the provenance graph. |
| `poll_interval` | `Int` | no | `30` | Seconds between status-check requests. |
| `download_timeout` | `Int` | no | `600` | Maximum seconds to wait for the archive after the job reports `done`. |

**Mutual-exclusion rules:** provide either `upper`+`lower` or `membtype` (not both, not neither); provide either `jobid_pdb` or `membrane_only=True` (not both, not neither). Violations are caught in `validate_inputs` before submission.

#### Outputs

Same as `CharmmGuiWorkChain`: `jobid` (`Str`) and `results` (`FolderData`).

#### Exit codes

Inherits codes 300–302 from `CharmmGuiWorkChain`, plus:

| Code | Label | Meaning |
|---|---|---|
| 400 | `ERROR_INVALID_INPUTS` | Parameter combination violates a mutual-exclusion rule |

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
