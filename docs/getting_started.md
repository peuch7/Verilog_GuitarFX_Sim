# Getting started

Three routes. Pick the one that matches your machine.

| You are on | Use |
|---|---|
| Windows | **The container.** Verilator has no usable native Windows build. |
| macOS | Native, via Homebrew. |
| Linux or WSL2 | Native, via apt. |

Whichever you pick, `make doctor` will tell you what is missing and the exact
command to fix it.

---

## Windows — VS Code devcontainer (recommended)

1. Install [Docker Desktop](https://docs.docker.com/desktop/install/windows-install/).
   Accept the WSL2 backend when it offers.
2. Install [VS Code](https://code.visualstudio.com/) and its **Dev Containers**
   extension.
3. **Clone the repository inside WSL2, not on `C:\`.** Open a WSL terminal and:

   ```bash
   git clone <repo-url> ~/VerilogSim
   ```

   This matters more than it looks. Docker bind mounts that cross the
   Windows/Linux filesystem boundary are roughly an order of magnitude slower,
   which is very noticeable when a simulation writes hundreds of thousands of
   samples. From Windows you can still reach those files at
   `\\wsl$\Ubuntu\home\<you>\VerilogSim` to play the output wavs.

4. Open that folder in VS Code (`code ~/VerilogSim` from the WSL terminal), then
   **Reopen in Container** when prompted.
5. In the container's terminal:

   ```bash
   make doctor
   make run effect=delay
   ```

The wav appears in `audio/output/` and is playable from Windows.

## Windows — without VS Code

Docker Desktop still required. From PowerShell in the repository:

```powershell
.\wavsim.ps1 setup
.\wavsim.ps1 run --effect delay --param mix=0.5
.\wavsim.ps1 test
.\wavsim.ps1 shell          # an interactive shell inside the container
```

`wavsim.ps1` passes anything it does not recognise straight to the CLI, so
`.\wavsim.ps1 info delay` works too.

---

## macOS

```bash
make setup
```

That installs Verilator and Icarus with Homebrew, creates `.venv`, installs the
Python package, and runs `make doctor`. If you do not have Homebrew, get it from
[brew.sh](https://brew.sh) first.

## Linux / WSL2

```bash
make setup
```

Installs `verilator iverilog build-essential python3-venv` with apt (it will ask
for sudo), then the same venv steps.

Already have the simulators and do not want the script touching them?

```bash
SKIP_TOOLCHAIN=1 make setup
```

**You never need to activate the venv.** Every make target uses `.venv/bin/python`
automatically when the directory exists.

---

## First run

```bash
make audio                    # synthesises the test wavs; no audio is committed
make run effect=delay
make compare effect=delay
make test
```

`make run` with no `wav=` generates and uses a short Karplus-Strong guitar
phrase, so there is something musical to listen to immediately.

Use your own audio with `wav=`:

```bash
make run effect=delay wav=~/Downloads/riff.wav params="delay_samples=14400,mix=0.45"
```

Any sample rate, bit depth or channel count is accepted — it is downmixed to
mono and resampled to 48 kHz on the way in.

---

## Trouble

**`make doctor` first.** It covers most of it.

**"verilator not found" on Windows.** Expected — use the container. There is no
supported native Windows path.

**Shell scripts fail inside the container with `\r` errors.** Your Git checked
out CRLF line endings. `.gitattributes` prevents this, but if the repo was
cloned before it existed:

```bash
git rm --cached -r . && git reset --hard
```

**Simulations feel very slow on Windows.** The repository is probably on `C:\`
instead of inside WSL2. See step 3 above.

**`make crosscheck` says a simulator is missing.** It needs both Verilator and
Icarus. Everything else works with just one.

**A build looks stale after editing RTL.** Rebuilds are triggered by file
timestamps. `make clean` forces a full rebuild.
