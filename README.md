# QIF Workshop

Six short notebooks that read a QIF document and show what it says: first the tolerances the drawing asks for, then the measurements of fifteen parts that were actually made. The point is not the pictures. It is that all of it was built with `ElementTree` and `numpy` in a few hundred lines, against an open standard, with no vendor software involved.

## Run order

Each notebook runs on its own kernel and can be shown on its own. They are numbered in the order they build on each other.

| | Notebook | What it shows | 3D |
|---|---|---|---|
| 00 | [`reading-qif`](notebooks/00-reading-qif.ipynb) | Open a document and follow its references by hand, from a callout and from a measurement down to a face. | no |
| 01 | [`tolerance-tightness`](notebooks/01-tolerance-tightness.ipynb) | **Design intent.** The part colored by how tightly each face is controlled, once per GD&T class. | yes |
| 02 | [`inspection-report`](notebooks/02-inspection-report.ipynb) | **Measured reality.** Build the results table, set aside the junk, and show one part as an inspector would. | no |
| 03 | [`across-parts`](notebooks/03-across-parts.ipynb) | All 15 parts: the pivot, bias beside scatter, and four holes under one callout. | no |
| 04 | [`results-on-the-part`](notebooks/04-results-on-the-part.ipynb) | The same results colored onto the part, with a slider to step through the parts. | yes |
| 05 | [`probe-points-and-form`](notebooks/05-probe-points-and-form.ipynb) | The probe points behind the numbers: coverage, the unprobed gap, and form. | charts |

**The four holes span 03 and 05.** 03 shows that four holes under one Ø8.73 callout vary very differently from part to part; 05 comes back to them to show their shape. Run 03 before 05 if you are telling that story.

The helpers the notebooks share (reading the XML, the joins, the results table, decoding probe points, meshing) are in [`notebooks/qifkit.py`](notebooks/qifkit.py). It is a plain module next to the notebooks, written to be read; 00 walks through it.

## The pipeline

```
  models/*.qif  ──→  qif-brep2mesh  ──→  points / triangles / qif_id  ──→  notebook
  B-rep + PMI + results      in memory, plain numpy                 join and render
```

Two stages, and nothing written to disk between them.

## The mesher: qif-brep2mesh

A QIF document stores the part's geometry as a B-rep: exact surfaces bounded by edges, not triangles. The 3D views need triangles, so the first stage converts one to the other with [qif-brep2mesh](https://github.com/QualityInformationFramework/qif-brep2mesh), a separate open-source project from the QIF organization.

It is the one stage this repository does not show you, so it is worth knowing it is there. `pip install -r requirements.lock` installs it like any other dependency, pinned to release v0.1. `qifkit.tessellate` calls it as a library and keeps the mesh in memory. It also has a command line that writes mesh QIF, VTK, PLY or OBJ; see its README.

## Setup

**Use Python 3.13, and ask for it by name** (`py -3.13` on Windows, `python3.13` elsewhere). On many machines the default Python is already 3.14, which is too new: `triangle`, which the mesher uses, publishes no wheel and no source distribution for 3.14, so 3.14 installs the notebook stack perfectly, and then fails at the mesher, which is the worst possible moment to find out. At the other end, the lockfile needs 3.12 or newer (its pinned numpy has no older wheels).

**Install from `requirements.lock`.** It pins every package, transitive ones included, to the set the notebooks were tested against, so a release the night before cannot break setup. It resolves on Linux, Windows and macOS. `requirements.txt` is the short, readable list the lock is generated from. Use it when changing dependencies, or on Python 3.11, which the lock does not support.

**Budget about 1.4 GB and a few minutes.** VTK alone is 639 MB, a monolithic wheel with no slim variant, and scipy adds another 110 MB. This looks like a small demo and does not install like one.

### Before you start

You need two things installed: **Python 3.13** and **Git**. Git is used to clone this repository, and by pip to fetch the mesher.

On Windows, both come from `winget`, which is built into Windows 10 and 11:

```powershell
winget install Python.Python.3.13
winget install Git.Git
```

Open a new terminal afterward so it sees them. Check that Python 3.13 is there (this does not need to be your default Python; the `py` launcher finds it by version and leaves any other Python alone):

```powershell
py -3.13 --version
```

On Linux and macOS, install Python 3.13 and Git with your package manager.

### Windows (PowerShell)

Open PowerShell in the folder where you want the workshop to live.

```powershell
git clone https://github.com/QualityInformationFramework/qif-workshop.git
cd qif-workshop

py -3.13 -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.lock

jupyter lab
```

Then open `notebooks/00-reading-qif.ipynb`. The prompt shows `(venv)` while the environment is active; run `venv\Scripts\Activate.ps1` again in any new terminal before `jupyter lab`.

If `Activate.ps1` fails with *running scripts is disabled on this system*, allow local scripts once and retry:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Or skip activation and call the tools by path: `venv\Scripts\pip install ...`, `venv\Scripts\jupyter lab`. In Command Prompt, use `venv\Scripts\activate.bat`.

### Linux and macOS

```bash
git clone https://github.com/QualityInformationFramework/qif-workshop.git
cd qif-workshop

python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.lock

jupyter lab
```

Then open `notebooks/00-reading-qif.ipynb`.

## Reading the output

**Tolerance tightness (01).** Four panels, one per GD&T class, on a shared color scale so they can be compared. Lower = tighter = more expensive to make. **Gray means the face is not controlled in that class**. This is normal, not an error, and the most common misreading of the picture.

**Measured results (02–04).** `fraction` is how much of its tolerance band a measurement consumed: 1.0 sits exactly on the limit, above 1.0 is out of tolerance. On the 3D view in 04, gray means the face carries no measured characteristic. A CMM measures features, not surfaces; 35 of 65 faces being measured is expected.

## The `qif_id` contract

One integer per mesh triangle, holding the QIF geometry entity id of the face it was tessellated from. Every per-face value 01 and 04 draw is a left join onto it, and both reach it through the same elements:

```
tolerance:   CharacteristicNominal ──→ FeatureNominal ──→ EntityInternalIds  ==  qif_id
measurement: CharacteristicItem ──→ FeatureItem ──→ FeatureNominal ──→ EntityInternalIds
```

A tolerance belongs to the callout, so it lands on every feature the callout covers. A measurement belongs to one application of it, so it lands on that feature only. Once the tolerance view exists, the results view is the same join entered one step earlier.

## The models

See [`models/README.md`](models/README.md). The short version: two parts, each with a plain MBD document and a measured one. The measured files are complete QIF documents (geometry, PMI **and** results together), which is why nothing has to be joined across files.

## Notes

- 01 and 04 use `pv.set_jupyter_backend('trame')` for a live viewport (set in `qifkit.start_viewer`). If a viewport never appears, it is most likely a locked-down machine that cannot open a websocket back to the kernel; `'html'` still orbits, `'static'` gives a plain image. The other four notebooks draw no 3D and are unaffected.
- Edits to `qifkit.py` take effect without restarting the kernel: every notebook loads the `autoreload` extension first.

## Acknowledgments

A big thanks to the [Digital Enterprise Center at Purdue Polytechnic](https://polytechnic.purdue.edu/digital-enterprise-center) for providing the parts used in this workshop.

## License

MIT. See [`LICENSE`](LICENSE). The `triangle` package, which the mesher depends on, has its own, more restrictive terms for commercial use; see the mesher's README.
