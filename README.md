# ImageSelector Cluster

Review images for a configurable two-cell cluster. On this Mac, double-click **Open-ImageSelector.command** in Finder. The launcher uses the project virtual environment when available, then the local Codex Python runtime.

## Install and run

Use Python 3.10 or newer with Tkinter (Tcl/Tk). Conda and virtual environments are optional. Run the commands below from the extracted project folder containing `app.py`.

### Windows (PowerShell)

```powershell
py -m tkinter
py -m pip install -r requirements.txt
py app.py
```

The first command opens a small Tk test window. Close it before continuing. If `py` is unavailable and `python` runs your Python installation, use `python` for all three commands.

### macOS (Terminal)

```bash
python3 -m tkinter
python3 -m pip install -r requirements.txt
python3 app.py
```

If pip reports an externally managed environment, create a project environment with `python3 -m venv .venv` on macOS or `py -m venv .venv` on Windows. Run the install and launch commands using `.venv/bin/python` on macOS or `.\.venv\Scripts\python.exe` in PowerShell.

To try the included synthetic images, add `--input example_images` to the launch command.

## Review images

1. Choose the image folder, the results CSV, and the two cell types for this batch. The default target is **CTC + Neutrophil**. Leaving the CSV field blank uses a target-specific name in the image folder, such as `cluster_review_CTC-Neutrophil.csv`.
2. At the first step, choose **No cluster**, **Exactly 2 cells**, **3 or more cells**, or **Uncertain**. **Exactly 2 cells** opens the second step on the current image. The other choices save and advance.
3. At the second step, choose **CTC + CTC**, the batch target, or **Others**. The first two choices save and advance. **Others** opens the third step on the current image.
4. At the third step, search or scroll through the remaining 26 two-cell combinations. Choose **Unknown** for an unidentified member, for example **CTC + Unknown**. Click **Save and next**, or double-click a combination. **Back to Step 2** lets you change the quick classification.

The number keys select the displayed choices. Use the arrow keys or **Previous** and **Next** to navigate. **Back to cluster size** returns to the first step on the current image. **Clear** removes the current annotation. **Q** or **Esc** closes the review.

To resume, select the same image folder, target, and CSV. The program opens the first incomplete image at its saved step. Earlier **Others** annotations remain valid. Navigate back to one to complete its exact combination in Step 3. Choose a separate CSV for a different target or an independent review of the same target. Use one review window per CSV.

The CSV records the cluster size decision, the second-step classification, and the batch target. Filter the `cell_combination` column for an exact pair. After saving Step 3, `classification` contains `Others` and `cell_combination` contains the selected pair. An unfinished Step 3 is saved as `Pending pair selection`.
